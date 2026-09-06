"""Emisión de invitaciones al portal: la única parte del código que ve el
token en texto plano.

``issue_invitation`` es upsert-on-pending: invitar de nuevo a un mail con una
invitación pendiente en el mismo cliente regenera ``token_hash`` y
``expires_at`` sobre la misma fila en vez de crear una segunda — así el link
viejo queda inválido de inmediato (Spec: Invitation Re-send) sin dejar filas
huérfanas cuando alguien reenvía por error.

``send_invitation_email`` es la función NOMBRADA que ``BackgroundTasks``
llama después de confirmar la transacción (nunca dentro de un ``async def``,
ver ``services/emails.py``). Corre en un hilo de threadpool, no en el request
que la encoló, así que abre su propia sesión con ``database.new_session()``
en vez de reusar la que cerró el router — D7 (registrar el resultado real del
envío, no asumir éxito por falta de excepción en el hilo principal).
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import new_session
from ..models import Client, PortalInvitation, now_utc
from ..security import generate_invitation_token, hash_invitation_token
from .emails import Email, send_email
from .error_log import record_error

logger = logging.getLogger(__name__)

# app/models.py::PortalInvitation.delivery_error es String(200); un mensaje
# más largo se corta acá para no chocar con el límite de la columna, y nunca
# se guarda un traceback completo (podría arrastrar detalle de conexión que no
# hace falta exponer en el panel).
DELIVERY_ERROR_MAX_LENGTH = 200


def issue_invitation(
    db: Session,
    *,
    client: Client,
    email: str,
    department_id: uuid.UUID | None,
    name: str = "",
    invited_by: uuid.UUID | None = None,
) -> tuple[PortalInvitation, str]:
    """Crea o refresca una invitación pendiente. Devuelve ``(fila, token_crudo)``.

    ``token_crudo`` solo existe acá, en la pila de quien llama, para componer
    el link (mail o respuesta): nunca se guarda, solo su digest (D1/D2).
    """
    normalized_email = email.lower()
    raw_token = generate_invitation_token()
    expires_at = now_utc() + timedelta(minutes=get_settings().invitation_token_minutes)

    invitation = db.scalar(
        select(PortalInvitation).where(
            PortalInvitation.client_id == client.id,
            PortalInvitation.email == normalized_email,
            PortalInvitation.accepted_at.is_(None),
        )
    )
    if invitation is not None:
        # Re-invite: mismo registro, token y vencimiento nuevos. El link
        # anterior queda inválido apenas se confirma (Spec: Invitation Re-send).
        invitation.department_id = department_id
        invitation.name = name
        invitation.token_hash = hash_invitation_token(raw_token)
        invitation.expires_at = expires_at
        invitation.invited_by = invited_by
        # Un reenvío merece su propia chance de entrega; no arrastrar el
        # fallo de la vez anterior.
        invitation.delivered_at = None
        invitation.delivery_error = None
        invitation.updated_at = now_utc()
    else:
        invitation = PortalInvitation(
            client_id=client.id,
            department_id=department_id,
            email=normalized_email,
            name=name,
            token_hash=hash_invitation_token(raw_token),
            expires_at=expires_at,
            invited_by=invited_by,
        )
        db.add(invitation)
    db.flush()
    return invitation, raw_token


def send_invitation_email(invitation_id: uuid.UUID, email: Email) -> None:
    """Wrapper nombrado alrededor de ``send_email`` para el dispatch en segundo
    plano (Constraint: smtplib async ban — esto corre en el hilo de
    ``BackgroundTasks``, nunca en el event loop).

    A diferencia de ``send_email`` (que no traga excepciones a propósito),
    este wrapper SÍ las captura: es el único lugar responsable de dejar
    constancia (D7). Abre su propia sesión porque corre después de que la
    request que encoló la tarea ya respondió y cerró la suya — reusar esa
    sesión desde otro hilo, o llamar a ``SessionLocal()`` directo, es
    exactamente lo que ``AGENTS.md``/``test_session_factory.py`` prohíben.
    Si la fila ya no existe (por ejemplo, se borró la dependencia entre medio
    — CASCADE, ver D5), no hay dónde escribir el resultado y no es un error:
    simplemente no queda nadie a quien avisarle.
    """
    db = new_session()
    try:
        invitation = db.get(PortalInvitation, invitation_id)
        if invitation is None:
            return
        try:
            send_email(email)
        except Exception as exc:  # noqa: BLE001 - cualquier fallo de entrega se registra, no se descarta
            logger.error("No se pudo entregar la invitación %s: %s", invitation_id, exc)
            invitation.delivery_error = f"{type(exc).__name__}: {exc}"[:DELIVERY_ERROR_MAX_LENGTH]
            invitation.delivered_at = None
            # Además de delivery_error (visible en el panel), una fila en el
            # registro nativo de errores: mismo fallo, capturado con su
            # traceback y con la agencia dueña de la invitación.
            record_error(
                source="invitations.email",
                capture_kind="explicit",
                exc=exc,
                agency_id=invitation.client.agency_id,
                subject_ref=f"invitation:{invitation_id}",
            )
        else:
            invitation.delivered_at = now_utc()
            invitation.delivery_error = None
        invitation.updated_at = now_utc()
        db.commit()
    finally:
        db.close()

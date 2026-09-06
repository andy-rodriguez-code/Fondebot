"""Emisión de invitaciones al portal: la única parte del código que ve el
token en texto plano.

``issue_invitation`` es upsert-on-pending: invitar de nuevo a un mail con una
invitación pendiente en el mismo cliente regenera ``token_hash`` y
``expires_at`` sobre la misma fila en vez de crear una segunda — así el link
viejo queda inválido de inmediato (Spec: Invitation Re-send) sin dejar filas
huérfanas cuando alguien reenvía por error.

``send_invitation_email`` es la función NOMBRADA que ``BackgroundTasks``
llama después de confirmar la transacción (nunca dentro de un ``async def``,
ver ``services/emails.py``). PR4 la extiende para capturar el error y grabar
``delivered_at``/``delivery_error`` en la fila; queda extraída a propósito
para que ese cambio sea agregar comportamiento, no separar código que hoy
vive inline en el router.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Client, PortalInvitation, now_utc
from ..security import generate_invitation_token, hash_invitation_token
from .emails import Email, send_email


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


def send_invitation_email(email: Email) -> None:
    """Wrapper nombrado alrededor de ``send_email`` para el dispatch en segundo
    plano (Constraint: smtplib async ban — esto corre en el hilo de
    ``BackgroundTasks``, nunca en el event loop).

    PR2 no captura el fallo: no hay todavía dónde dejar constancia (esa fila
    es ``delivery_error``, que PR4 agrega). Starlette registra cualquier
    excepción de una tarea en segundo plano en el log del proceso; nada de
    esto revierte la invitación, que ya quedó confirmada antes de encolar el
    envío.
    """
    send_email(email)

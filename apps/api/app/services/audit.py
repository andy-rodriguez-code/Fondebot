"""Registro de acciones sensibles.

Se escribe desde el handler que hizo el cambio, en la MISMA sesión y antes del
commit: así la fila de auditoría y el cambio que describe entran juntos o no
entra ninguno. Un registro que puede quedar sin la acción, o una acción que
puede quedar sin registro, no sirve para la pregunta que se le va a hacer.

Eso es lo contrario de ``error_log.record_error``, que abre su propia sesión a
propósito porque escribe cuando la del pedido ya se rompió. Acá la sesión está
sana y el cambio todavía no se guardó, que es exactamente cuando conviene.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ..models import AuditLog, PortalUser, User

# Lo que se registra. Son cadenas y no un enum porque viajan a la interfaz y se
# guardan tal cual: un valor viejo en una fila de hace un año tiene que seguir
# leyéndose aunque el código ya no lo escriba.
PROVIDER_CREDENTIALS_CHANGED = "provider.credentials_changed"
PROVIDER_CREDENTIALS_REMOVED = "provider.credentials_removed"
PORTAL_USER_CREATED = "portal_user.created"
PORTAL_USER_UPDATED = "portal_user.updated"
AGENT_INSTRUCTIONS_CHANGED = "agent.instructions_changed"


def _actor(actor: User | PortalUser | None) -> tuple[str, uuid.UUID | None, str]:
    """Quién actuó, resuelto a texto acá y no con un join después.

    El nombre se copia tal como es ahora: si mañana se borra la cuenta, la fila
    tiene que seguir diciendo quién fue. Ese es justamente el momento en que
    alguien la va a leer.
    """
    if actor is None:
        return "system", None, "system"
    label = (getattr(actor, "email", "") or getattr(actor, "name", "") or "")[:180]
    if isinstance(actor, PortalUser):
        return "portal_user", actor.id, label
    return "user", actor.id, label


def record(
    db: Session,
    *,
    agency_id: uuid.UUID,
    actor: User | PortalUser | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None = None,
    target_label: str = "",
) -> None:
    """Anota una acción. No hace commit: lo hace quien llamó, con su cambio.

    Nunca se le pasa el detalle de lo que cambió. En un cambio de credencial,
    "lo que cambió" ES la credencial.
    """
    actor_type, actor_id, actor_label = _actor(actor)
    db.add(
        AuditLog(
            agency_id=agency_id,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_label=actor_label,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_label=(target_label or "")[:180],
        )
    )

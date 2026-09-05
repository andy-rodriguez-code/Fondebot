"""CRUD for a client's departments (the WhatsApp entry menu).

Two invariants live here rather than in the caller: the agent answering a
department must belong to the same client, and a client has at most one entry
department. The second one is also a partial unique index, so setting a new
entry clears the old one first instead of tripping the constraint.

``enabled`` is about the menu, not about answering. A reception that only exists
to reply while the contact is choosing is taken out of the menu with
``enabled=False`` and still answers, which is how a client ends up offering
exactly its real departments as buttons.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, Client, Department, PortalInvitation, PortalUser, User, now_utc
from ..schemas import InvitationOut
from ..schemas_departments import DepartmentIn, DepartmentOut, DepartmentUpdate
from ..services.emails import build_invitation_email, email_enabled
from ..services.invitations import issue_invitation, send_invitation_email
from ..slugs import slugify


router = APIRouter(prefix="/clients/{client_id}/departments", tags=["Departments"])


def _client(db: Session, user: User, client_id: uuid.UUID) -> Client:
    client = db.scalar(select(Client).where(Client.id == client_id, Client.agency_id == user.agency_id))
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _department(db: Session, client: Client, department_id: uuid.UUID) -> Department:
    department = db.scalar(
        select(Department)
        .options(joinedload(Department.agent))
        .where(Department.id == department_id, Department.client_id == client.id)
    )
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")
    return department


def _validate_agent(db: Session, client: Client, agent_id: uuid.UUID) -> None:
    if not db.scalar(select(Agent.id).where(Agent.id == agent_id, Agent.client_id == client.id)):
        raise HTTPException(status_code=422, detail="That agent does not belong to this client")


def _unique_slug(db: Session, client: Client, name: str, *, exclude_id: uuid.UUID | None = None) -> str:
    base = slugify(name)[:56] or "dependencia"
    candidate = base
    for attempt in range(2, 100):
        query = select(Department.id).where(Department.client_id == client.id, Department.slug == candidate)
        if exclude_id:
            query = query.where(Department.id != exclude_id)
        if not db.scalar(query):
            return candidate
        candidate = f"{base}-{attempt}"
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _clear_other_entries(db: Session, client: Client, keep_id: uuid.UUID | None) -> None:
    """Only one department greets. Demote whoever held the role before."""
    for row in db.scalars(
        select(Department).where(Department.client_id == client.id, Department.is_entry.is_(True))
    ).all():
        if row.id != keep_id:
            row.is_entry = False
    db.flush()


def _out(department: Department, invitation: PortalInvitation | None = None) -> DepartmentOut:
    data = DepartmentOut.model_validate(department)
    data.agent_name = department.agent.name if department.agent else None
    if invitation is not None:
        data.invitation = _read_invitation_out(invitation)
    return data


def _assert_no_active_portal_user(db: Session, client: Client, email: str) -> None:
    """Espejo del chequeo de ``create_portal_user`` (Spec: Duplicate Portal-User
    Handling). Solo bloquea contra un miembro ACTIVO del MISMO cliente: la
    misma dirección en otro cliente está permitida, porque el índice único de
    ``portal_users`` es por cliente."""
    existing = db.scalar(
        select(PortalUser.id).where(
            PortalUser.client_id == client.id, PortalUser.email == email, PortalUser.is_active.is_(True)
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="That e-mail is already on this portal")


def _accept_url(client: Client, raw_token: str) -> str:
    return f"{get_settings().frontend_url}/portal/{client.portal_slug}/invite?token={raw_token}"


def _invitation_out(invitation: PortalInvitation, raw_token: str, client: Client) -> InvitationOut:
    # "failed" solo lo agrega la lectura de list_departments (ver
    # _read_invitation_out), una vez que el envío en segundo plano tuvo tiempo
    # de correr y fallar; acá, recién creada o reenviada, es "sent" o "manual".
    delivery = "sent" if email_enabled() else "manual"
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        expires_at=invitation.expires_at,
        delivery=delivery,
        accept_url=None if email_enabled() else _accept_url(client, raw_token),
    )


def _read_invitation_out(invitation: PortalInvitation) -> InvitationOut:
    """Serializa una invitación pendiente para una LECTURA (``list_departments``).

    A diferencia de ``_invitation_out`` (creación/reenvío), acá no hay token
    crudo disponible — nunca se guarda (D1/D2) — así que ``accept_url`` queda
    siempre en ``None``: no hay forma de reconstruir el link, y devolverlo en
    un endpoint de listado tampoco sería correcto. ``delivery`` refleja lo que
    de verdad pasó en el envío en segundo plano (D7), no la promesa optimista
    del momento de la creación.
    """
    if invitation.delivery_error:
        delivery = "failed"
    elif invitation.delivered_at is not None:
        delivery = "sent"
    else:
        # Todavía no corrió (o no hay proveedor) el envío en segundo plano:
        # misma regla optimista que al crear.
        delivery = "sent" if email_enabled() else "manual"
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        expires_at=invitation.expires_at,
        delivery=delivery,
        accept_url=None,
    )


def _pending_invitations_by_department(
    db: Session, client: Client, department_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PortalInvitation]:
    """La invitación pendiente más reciente de cada dependencia, en una sola
    consulta (evita N+1 en ``list_departments``). El caso normal tiene a lo
    sumo una fila pendiente por dependencia; nada en el esquema lo impide
    (la unicidad es por cliente+mail, no por dependencia), así que si llegara
    a haber más de una esto se queda con la más nueva."""
    if not department_ids:
        return {}
    rows = db.scalars(
        select(PortalInvitation)
        .where(
            PortalInvitation.client_id == client.id,
            PortalInvitation.department_id.in_(department_ids),
            PortalInvitation.accepted_at.is_(None),
        )
        .order_by(PortalInvitation.created_at.desc())
    ).all()
    latest: dict[uuid.UUID, PortalInvitation] = {}
    for row in rows:
        latest.setdefault(row.department_id, row)
    return latest


def _queue_invitation_email(
    background_tasks: BackgroundTasks,
    client: Client,
    department: Department | None,
    invitation: PortalInvitation,
    raw_token: str,
) -> None:
    """Encola el envío para después de confirmar la transacción.

    ``BackgroundTasks`` corre esta llamada en un hilo de threadpool, nunca en
    el event loop (Constraint: smtplib async ban) — ver
    ``services/emails.py`` y ``send_invitation_email``.
    """
    if not email_enabled():
        return
    email = build_invitation_email(invitation.email, client, department, _accept_url(client, raw_token))
    background_tasks.add_task(send_invitation_email, invitation.id, email)


@router.get("", response_model=list[DepartmentOut])
def list_departments(
    client_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    client = _client(db, user, client_id)
    rows = db.scalars(
        select(Department)
        .options(joinedload(Department.agent))
        .where(Department.client_id == client.id)
        .order_by(Department.position, Department.name)
    ).all()
    pending_by_department = _pending_invitations_by_department(db, client, [row.id for row in rows])
    return [_out(row, pending_by_department.get(row.id)) for row in rows]


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    client_id: uuid.UUID,
    payload: DepartmentIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    _validate_agent(db, client, payload.agent_id)
    invite_email = payload.invite_email.lower() if payload.invite_email else None
    if invite_email:
        _assert_no_active_portal_user(db, client, invite_email)
    is_first = not db.scalar(select(Department.id).where(Department.client_id == client.id))
    department = Department(
        client_id=client.id,
        agent_id=payload.agent_id,
        name=payload.name,
        slug=_unique_slug(db, client, payload.name),
        description=payload.description,
        # La primera dependencia es la de entrada aunque no lo pidan: un menú
        # sin recepción deja al contacto sin nadie que le conteste.
        is_entry=payload.is_entry or is_first,
        enabled=payload.enabled,
        position=payload.position,
    )
    if department.is_entry:
        _clear_other_entries(db, client, None)
    db.add(department)
    db.flush()

    invitation, raw_token = (None, None)
    if invite_email:
        # Dependencia + invitación en una sola transacción (Spec: Optional
        # Invitation On Department Creation); el envío recién se encola
        # después de que ambas quedan confirmadas.
        invitation, raw_token = issue_invitation(
            db, client=client, email=invite_email, department_id=department.id,
            name=payload.invite_name, invited_by=user.id,
        )
    db.commit()
    db.refresh(department)

    out = _out(department)
    if invitation is not None:
        db.refresh(invitation)
        _queue_invitation_email(background_tasks, client, department, invitation, raw_token)
        out = out.model_copy(update={"invitation": _invitation_out(invitation, raw_token, client)})
    return out


@router.post(
    "/{department_id}/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED
)
def resend_invitation(
    client_id: uuid.UUID,
    department_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reenvía la invitación pendiente de esta dependencia (Spec: Invitation
    Re-send). Reusa el mail que ya estaba en la fila pendiente: reenviar no
    es invitar a alguien distinto, es volver a mandar el mismo link."""
    client = _client(db, user, client_id)
    department = _department(db, client, department_id)
    pending = db.scalar(
        select(PortalInvitation).where(
            PortalInvitation.client_id == client.id,
            PortalInvitation.department_id == department.id,
            PortalInvitation.accepted_at.is_(None),
        )
    )
    if not pending:
        raise HTTPException(status_code=404, detail="This department has no pending invitation to resend")
    invitation, raw_token = issue_invitation(
        db, client=client, email=pending.email, department_id=department.id,
        name=pending.name, invited_by=user.id,
    )
    db.commit()
    db.refresh(invitation)
    _queue_invitation_email(background_tasks, client, department, invitation, raw_token)
    return _invitation_out(invitation, raw_token, client)


@router.patch("/{department_id}", response_model=DepartmentOut)
def update_department(
    client_id: uuid.UUID,
    department_id: uuid.UUID,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    department = _department(db, client, department_id)
    updates = payload.model_dump(exclude_unset=True)
    if "agent_id" in updates and updates["agent_id"]:
        _validate_agent(db, client, updates["agent_id"])
    if updates.get("is_entry"):
        _clear_other_entries(db, client, department.id)
    elif updates.get("is_entry") is False and department.is_entry:
        raise HTTPException(
            status_code=422,
            detail="Mark another department as the entry one instead of leaving this client without a reception.",
        )
    if "name" in updates and updates["name"] and updates["name"] != department.name:
        department.slug = _unique_slug(db, client, updates["name"], exclude_id=department.id)
    for key, value in updates.items():
        if value is not None:
            setattr(department, key, value)
    department.updated_at = now_utc()
    db.commit()
    db.refresh(department)
    return _out(department)


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department(
    client_id: uuid.UUID,
    department_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    department = _department(db, client, department_id)
    siblings = db.scalar(
        select(Department.id).where(Department.client_id == client.id, Department.id != department.id)
    )
    if department.is_entry and siblings:
        raise HTTPException(
            status_code=422,
            detail="Mark another department as the entry one before deleting this one.",
        )
    # Las conversaciones y las personas del portal apuntan acá con SET NULL:
    # borrar una dependencia devuelve sus casos a la vista de todos en vez de
    # llevárselos puestos.
    db.delete(department)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

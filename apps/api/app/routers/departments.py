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

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, Client, Department, User, now_utc
from ..schemas_departments import DepartmentIn, DepartmentOut, DepartmentUpdate
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


def _out(department: Department) -> DepartmentOut:
    data = DepartmentOut.model_validate(department)
    data.agent_name = department.agent.name if department.agent else None
    return data


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
    return [_out(row) for row in rows]


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    client_id: uuid.UUID,
    payload: DepartmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    client = _client(db, user, client_id)
    _validate_agent(db, client, payload.agent_id)
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
    db.commit()
    db.refresh(department)
    return _out(department)


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

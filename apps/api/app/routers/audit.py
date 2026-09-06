"""Lectura del registro de auditoría.

Solo lectura, y a propósito: no hay endpoint para editar ni para borrar una
fila. Un registro que quien administra puede corregir no responde la pregunta
para la que existe.

Lo único que borra filas es el ``ON DELETE CASCADE`` desde ``agencies``, que es
el borrado de toda la cuenta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import AuditLog, User
from ..schemas import AuditEntryOut

router = APIRouter(prefix="/audit", tags=["Auditoría"])


@router.get("", response_model=list[AuditEntryOut])
def list_audit_entries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Lo último que pasó en esta agencia, de lo más nuevo a lo más viejo.

    El filtro por ``agency_id`` es la frontera entre inquilinos, igual que en
    todos los demás routers, y el índice de la tabla lo tiene como primera
    columna justamente para esta consulta.
    """
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.agency_id == user.agency_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return rows

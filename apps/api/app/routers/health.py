"""Superficie de lectura de salud y errores nativos (Slice 2a).

Dos endpoints, ninguno relacionado con la liveness de ``main.py``:

``GET /api/health/ready`` toca la base de datos y es pública/sin autenticar
(D6). ``GET /api/health/errors`` es autenticada y agency-scoped (D9). Ninguno
de los dos hace ack/resolve, búsqueda ni filtros — eso es un no-goal del spec.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select, text, tuple_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import ErrorEvent, User
from ..schemas import ErrorEventOut

router = APIRouter(prefix="/health", tags=["System"])


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    """Readiness: distinta de ``GET /health`` (liveness, en ``main.py``), que
    NO toca la base a propósito — la usa el healthcheck de
    ``docker-compose.yml`` del que dependen ``web`` y ``whatsapp``, y
    repointearla acoplaría un blip de base de datos a un reinicio en cascada
    de los tres servicios.

    Pública, sin autenticar y sin límite de tasa: debe seguir siendo
    pollable. Por eso la respuesta revela deliberadamente solo un booleano
    con forma fija — nunca el mensaje de la excepción, el driver, el host,
    el usuario ni ningún valor de configuración. No llama a ``record_error``:
    un monitor sondeando cada pocos segundos contra una base caída no puede
    convertirse en un amplificador de escritura.
    """
    try:
        db.execute(text("SET LOCAL statement_timeout = '3s'"))
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - opacidad deliberada, ver docstring
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "checks": {"database": "error"}},
        )
    return {"status": "ok", "checks": {"database": "ok"}}


@router.get("/errors", response_model=list[ErrorEventOut])
def list_errors(
    limit: int = Query(default=50, ge=1, le=100),
    before: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Más nuevo primero, sin ack/resolve. Sin gate por rol: ``User.role``
    queda sin leer a propósito (auditoría P-3, cambio aparte).

    Una fila con ``agency_id`` nulo es visible para toda persona autenticada:
    decisión de producto asentada, no un descuido — son justo las fallas
    silenciosas que motivan esta feature (una respuesta de WhatsApp
    debounceada que nunca salió). No se redacta acá: ``message``/``traceback``
    ya llegaron redactados desde ``record_error`` en el momento de escribir;
    redactar de nuevo en la lectura sería redundante.

    Paginación por cursor (D9), no ``limit``/``offset``: esta tabla es
    append-only y se escribe mientras se pagina, justo durante un incidente
    -que es el único momento en que alguien la pagina-. ``before`` es el id
    de la última fila vista; se resuelve su ``occurred_at`` y se compara por
    tupla ``(occurred_at, id)`` para no perder ni duplicar filas en un
    empate de reloj.
    """
    query = select(ErrorEvent).where(
        or_(ErrorEvent.agency_id == user.agency_id, ErrorEvent.agency_id.is_(None))
    )
    if before is not None:
        cursor = db.get(ErrorEvent, before)
        if cursor is None:
            # La fila del cursor ya no está: la purga corre cada hora, y quien
            # pagina esta tabla lo hace justo durante el incidente en el que la
            # purga se dispara. Ignorar el cursor volvería a la primera página y
            # quien pagina vería la misma página para siempre; lo honesto es
            # decir que lo que venía recorriendo se terminó.
            return []
        query = query.where(
            tuple_(ErrorEvent.occurred_at, ErrorEvent.id) < tuple_(cursor.occurred_at, cursor.id)
        )
    rows = db.scalars(
        query.order_by(ErrorEvent.occurred_at.desc(), ErrorEvent.id.desc()).limit(limit)
    ).all()
    return [
        ErrorEventOut.model_validate(row).model_copy(update={"is_global": row.agency_id is None})
        for row in rows
    ]

"""Registro nativo de sitio y errores: sin proveedor externo, sin SDK, sin
seam de reenvío. Tres funciones:

``redact()`` es pura — recibe los secretos como argumento y nunca lee
``get_settings()`` — para que una prueba pueda afirmar su comportamiento con
literales, sin monkeypatch. ``record_error()`` nunca lanza ni recursa: abre su
propia sesión con ``new_session()`` (nunca ``SessionLocal()`` directo, ver
``AGENTS.md``/``tests/test_session_factory.py``) porque la sesión del pedido
que está fallando puede ser justo lo que se rompió. ``purge_error_events()``
aplica una ventana de tiempo Y un tope de filas en el mismo pase: una ráfaga
cabe entera dentro de la ventana, así que la ventana sola no alcanza.
"""

from __future__ import annotations

import logging
import re
import traceback as traceback_module
import uuid
from contextvars import ContextVar
from datetime import timedelta
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import new_session
from ..models import ErrorEvent, now_utc

logger = logging.getLogger(__name__)

REDACTED = "[redacted]"
# str(exc)[:400] es la convención existente en whatsapp_inbound.py:378,477.
MESSAGE_MAX_LENGTH = 400
TRACEBACK_MAX_LENGTH = 8000
# Espejo de los largos de columna de ErrorEvent (models.py). Todo lo que entra
# se recorta acá: un valor más largo que su columna hace fallar el INSERT del
# error, y la fila se pierde justo cuando más se la necesita.
REQUEST_METHOD_MAX_LENGTH = 10
REQUEST_PATH_MAX_LENGTH = 300
SUBJECT_REF_MAX_LENGTH = 120
EXCEPTION_TYPE_MAX_LENGTH = 120

# Un secreto de menos de 8 caracteres se salta, incluida la cadena vacía:
# smtp_password legítimamente vale "" (config.py) y "hola".replace("", "X")
# devuelve "XhXoXlXaX" — un guard ausente vuelve confeti cualquier mensaje.
_MIN_SECRET_LENGTH = 8

# Formas conocidas de secreto, para el caso en que el valor no es nuestro
# (una clave de un tercero que nunca tuvimos en INSECURE_VALUES/settings).
_BEARER_PATTERN = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9]{8,}")
# El grupo 1 (la etiqueta) se conserva a propósito: quien opera necesita saber
# que ACÁ había un token, no solo que algo fue removido.
# ``['\"]?`` entre la etiqueta y el separador: en el repr de un dict de Python
# la comilla de cierre se mete en el medio — ``'password_hash': '...'`` — y sin
# eso el patrón no matchea justo donde más importa.
_LABELLED_PATTERN = re.compile(
    r"(api[_-]?key|token|password|secret|authorization)\w*['\"]?\s*[=:]\s*\S+", re.IGNORECASE
)
# SQLAlchemy le pega "[SQL: ...] [parameters: {...}]" al texto de cualquier
# StatementError, y esos parámetros son la fila que se estaba escribiendo. El
# engine ya lo apaga con hide_parameters=True (database.py); esto es la segunda
# línea, para cualquier excepción que llegue de otro engine o de otra versión.
_SQL_TAIL_PATTERN = re.compile(r"\[SQL:.*", re.DOTALL)
_QUERY_STRING_PATTERN = re.compile(r"(https?://[^\s\"'<>]+)\?[^\s\"'<>]*")

# Reentrancia: hoy no es alcanzable (el except de record_error no vuelve a
# llamar a record_error), pero la propiedad debe sobrevivir a que alguien más
# adelante agregue una captura dentro de esa misma rama de fallo.
_recording: ContextVar[bool] = ContextVar("error_log_recording", default=False)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Compone → redacta. Quien llama trunca después (D8): truncar antes puede
    partir un secreto a la mitad, y la mitad que sobrevive ya no matchea ni el
    valor literal ni ninguna forma conocida — queda guardada para siempre.
    """
    result = text
    # 1) Sustitución literal, de más largo a más corto: si un secreto corto
    #    fuera subcadena de otro, ir del más corto al más largo dejaría un
    #    resto del secreto más largo sin cubrir.
    literal_values = sorted(
        {value for value in secrets if len(value) >= _MIN_SECRET_LENGTH}, key=len, reverse=True
    )
    for value in literal_values:
        result = result.replace(value, REDACTED)
    # 2) Formas conocidas de secreto, sin conocer el valor.
    result = _BEARER_PATTERN.sub(REDACTED, result)
    result = _SK_PATTERN.sub(REDACTED, result)
    result = _LABELLED_PATTERN.sub(rf"\1={REDACTED}", result)
    # 3) Ninguna query string se guarda jamás, matchee o no alguna forma.
    result = _QUERY_STRING_PATTERN.sub(rf"\1?{REDACTED}", result)
    # 4) Y nada de lo que SQLAlchemy adjunta después de "[SQL:": ahí viaja la
    #    consulta con sus parámetros ligados, o sea la fila entera.
    result = _SQL_TAIL_PATTERN.sub(REDACTED, result)
    return result


# Se deriva de los campos de Settings en vez de listarlos a mano: una lista
# escrita a mano se desactualiza el día que alguien agrega un secreto nuevo, y
# el costo de ese olvido es un secreto guardado en claro para siempre. Redactar
# de más nunca hace daño; redactar de menos sí.
#     "database_url" no contiene ninguna de estas palabras y sin embargo lleva
#     la contraseña de Postgres adentro, así que va aparte: es exactamente el
#     agujero que una lista derivada existe para no tener.
_SECRET_FIELD_WORDS = ("secret", "password", "token", "key", "database_url")


def _live_secrets() -> list[str]:
    """La única parte impura: qué secretos vivos existen ahora mismo.

    Los enteros quedan afuera por el filtro de tipo (``access_token_minutes``,
    ``invitation_token_minutes``), y los vacíos los descarta después el largo
    mínimo de :func:`redact`.
    """
    settings = get_settings()
    return [
        value
        for name in type(settings).model_fields
        if isinstance(value := getattr(settings, name, None), str)
        and any(word in name for word in _SECRET_FIELD_WORDS)
    ]


def record_error(
    *,
    source: str,
    capture_kind: str,
    exc: BaseException,
    agency_id: uuid.UUID | None = None,
    request_method: str | None = None,
    request_path: str | None = None,
    subject_ref: str | None = None,
) -> None:
    """Registra una fila. NUNCA lanza, NUNCA recursa (D5).

    ``BaseException`` (``CancelledError``, ``KeyboardInterrupt``) se deja
    pasar a propósito: tragar una cancelación dentro de una tarea de lifespan
    colgaría el apagado. El traceback sale de ``exc`` con
    ``traceback.format_exception`` (Python 3.12), nunca de
    ``traceback.format_exc()``: esta última lee la excepción AMBIENTE, y
    dentro de un ``add_done_callback`` no hay ninguna en curso — devolvería el
    literal ``"NoneType: None"``.
    """
    if _recording.get():
        return
    token = _recording.set(True)
    try:
        secrets = _live_secrets()
        message = redact(f"{type(exc).__name__}: {exc}", secrets)[:MESSAGE_MAX_LENGTH]
        # format_exception pone los frames externos primero y el más interno
        # -la respuesta a "dónde rompió"- al final, por eso acá se trunca por
        # la cola en vez de por la cabeza.
        stack = redact("".join(traceback_module.format_exception(exc)), secrets)
        stack = stack[-TRACEBACK_MAX_LENGTH:]
        db = new_session()
        try:
            db.add(
                ErrorEvent(
                    agency_id=agency_id,
                    source=source,
                    capture_kind=capture_kind,
                    exception_type=type(exc).__name__[:EXCEPTION_TYPE_MAX_LENGTH],
                    message=message,
                    traceback=stack,
                    # Truncados como message y traceback, y no pasados tal
                    # cual: la ruta la elige quien llama, y una más larga que
                    # la columna hace fallar el INSERT del propio error. La
                    # fila se perdía en silencio, o sea justo el caso que este
                    # registro existe para no dejar pasar.
                    request_method=(request_method or None) and request_method[:REQUEST_METHOD_MAX_LENGTH],
                    request_path=(request_path or None) and request_path[:REQUEST_PATH_MAX_LENGTH],
                    subject_ref=(subject_ref or None) and subject_ref[:SUBJECT_REF_MAX_LENGTH],
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception:
        # Si la base es justo lo que está roto, esto degrada a un traceback de
        # consola y se descarta: un registro de errores no puede sobrevivir a
        # la base de datos, y fingir lo contrario sería un segundo medio de
        # almacenamiento sin revisar.
        logger.exception("No se pudo registrar el error de %s/%s", source, capture_kind)
    finally:
        _recording.reset(token)


def purge_error_events(db: Session, *, days: int, max_rows: int) -> int:
    """Borra por ventana de tiempo Y por tope de filas, en el mismo pase.

    Ninguno de los dos límites alcanza solo: una ráfaga cabe entera dentro de
    la ventana de retención (el tope la acota), y una instancia tranquila
    nunca llega al tope (la ventana igual la achica). ``0`` desactiva ese
    límite en particular; los dos en ``0`` desactiva la purga completa.
    """
    removed = 0
    if days > 0:
        cutoff = now_utc() - timedelta(days=days)
        result = db.execute(delete(ErrorEvent).where(ErrorEvent.occurred_at < cutoff))
        removed += result.rowcount
    if max_rows > 0:
        # DESC, DESC (no solo occurred_at): una ráfaga dentro del mismo tick
        # de reloj vuelve el orden no determinístico si se rompe el empate
        # solo por tiempo, y eso vuelve inestables tanto el barrido como su
        # prueba.
        stale_ids = (
            select(ErrorEvent.id)
            .order_by(ErrorEvent.occurred_at.desc(), ErrorEvent.id.desc())
            .offset(max_rows)
        )
        result = db.execute(delete(ErrorEvent).where(ErrorEvent.id.in_(stale_ids)))
        removed += result.rowcount
    db.commit()
    return removed

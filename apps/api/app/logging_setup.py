"""Un identificador por pedido, en cada línea de log que ese pedido produce.

El problema que resuelve: hasta acá los logs eran texto suelto sin nada que los
atara entre sí. Cuando alguien reporta "se rompió a las tres", no hay forma de
separar sus líneas de las de todos los demás pedidos que pasaron al mismo
tiempo. Con un identificador compartido, se filtra por él y aparece esa
historia sola.

Se implementa acá y no con una librería por la misma razón que el registro de
errores es nativo: son treinta líneas, y una dependencia más en la imagen que
se publica se paga para siempre.

``ContextVar`` y no una variable global porque el valor tiene que ser distinto
por pedido concurrente. Es también lo que hace que funcione en los handlers
``def`` que FastAPI corre en el threadpool: ``contextvars`` viaja al hilo con
el contexto, así que ahí adentro se sigue leyendo el identificador correcto.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar

# Vacío significa "fuera de un pedido": un barrido en segundo plano, el
# arranque. Esas líneas siguen saliendo, solo que sin identificador.
_request_id: ContextVar[str] = ContextVar("request_id", default="")

# Un identificador que viene de afuera termina dentro de los logs, así que se
# acepta solo si tiene una forma inofensiva. Sin esto, quien llama elige qué se
# escribe en el archivo de logs, y ahí puede meter saltos de línea y fabricar
# entradas enteras que nunca ocurrieron.
_SAFE_ID = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")


def current_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str | None) -> str:
    """Fija el identificador del pedido y devuelve el que quedó.

    Se respeta el que llegue por cabecera —así una traza que empezó en otro
    servicio no se corta acá— pero solo si pasa la validación de forma.
    """
    candidate = (value or "").strip()
    resolved = candidate if _SAFE_ID.match(candidate) else uuid.uuid4().hex[:16]
    _request_id.set(resolved)
    return resolved


class RequestIdFilter(logging.Filter):
    """Pone ``request_id`` en cada registro, incluidos los de uvicorn.

    Es un filtro y no un formateador porque un formateador que referencia un
    campo inexistente lanza, y los registros que emite una librería de terceros
    nunca lo traen.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Una línea, un objeto JSON. Para quien manda los logs a algún lado."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"


def configure_logging(*, log_format: str = "text", level: str = "INFO") -> None:
    """Deja la raíz con un solo handler, con el filtro puesto.

    Se reemplazan los handlers en vez de agregar uno: uvicorn instala los
    suyos, y sumar otro imprimiría cada línea dos veces.
    """
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if log_format.lower() == "json" else logging.Formatter(TEXT_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn se configura aparte y con propagate en False, así que sin esto
    # sus líneas de acceso salen con el formato viejo y sin identificador.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [handler]
        uvicorn_logger.propagate = False

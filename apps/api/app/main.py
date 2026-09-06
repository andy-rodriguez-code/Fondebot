import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import new_session
from .services.conversation_state import resolve_idle_ai_conversations
from .services.error_log import purge_error_events, record_error
from .routers import (
    agency,
    audit,
    agent_tools,
    agents,
    auth,
    catalog,
    clients,
    conversations,
    dashboard,
    departments,
    domains,
    health,
    mobile,
    portal,
    providers,
    whatsapp,
    whatsapp_cloud,
    whatsapp_cloud_webhook,
    widget,
)


settings = get_settings()
logger = logging.getLogger(__name__)

AUTO_RESOLVE_SWEEP_SECONDS = 15 * 60
# No es una Setting como error_log_retention_days/error_log_max_rows: es el
# ritmo del barrido, no un límite de negocio. AUTO_RESOLVE_SWEEP_SECONDS sigue
# el mismo criterio.
ERROR_LOG_SWEEP_SECONDS = 60 * 60


async def _auto_resolve_loop() -> None:
    """Cierra las conversaciones de IA ociosas por temporizador, mientras la app viva."""
    while True:
        await asyncio.sleep(AUTO_RESOLVE_SWEEP_SECONDS)
        try:
            with new_session() as db:
                closed = resolve_idle_ai_conversations(db, hours=get_settings().auto_resolve_after_hours)
            if closed:
                logger.info("Auto-resolved %d idle AI conversation(s)", closed)
        except Exception as exc:  # noqa: BLE001 - una pasada fallida no debe frenar la siguiente
            logger.exception("Auto-resolve sweep failed")
            record_error(source="conversations.auto_resolve", capture_kind="explicit", exc=exc)


async def _error_log_purge_loop() -> None:
    """Purga ``error_events`` por ventana de tiempo y tope de filas, mientras la
    app viva. Tarea separada de ``_auto_resolve_loop``: la retención del
    registro de errores no puede depender en silencio de que otra feature
    (el auto-resolve) esté habilitada."""
    while True:
        await asyncio.sleep(ERROR_LOG_SWEEP_SECONDS)
        try:
            error_settings = get_settings()
            with new_session() as db:
                purge_error_events(
                    db, days=error_settings.error_log_retention_days, max_rows=error_settings.error_log_max_rows
                )
        except Exception as exc:  # noqa: BLE001 - una pasada fallida no debe frenar la siguiente
            logger.exception("Error log purge sweep failed")
            # Como mucho una fila por pasada fallida: el barrido que existe
            # para achicar la tabla no puede ser su mayor escritor.
            record_error(source="error_log.purge", capture_kind="explicit", exc=exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    sweeper = asyncio.create_task(_auto_resolve_loop()) if settings.auto_resolve_after_hours > 0 else None
    purger = asyncio.create_task(_error_log_purge_loop())
    try:
        yield
    finally:
        if sweeper:
            sweeper.cancel()
        purger.cancel()


class ErrorCaptureMiddleware:
    """ASGI puro — deliberadamente NO ``@app.exception_handler(Exception)``.

    Starlette rutea ese decorador a ``ServerErrorMiddleware.handler``, que
    debe DEVOLVER una Response. Un handler que relanza nunca llega al
    ``raise exc`` propio de esa capa: no se inició ninguna respuesta y el
    cliente recibe la conexión cortada en vez del 500 de siempre. Acá se
    registra y se relanza tal cual, sin tocar la respuesta ni bufferizarla
    (a diferencia de ``BaseHTTPMiddleware``).

    ``HTTPException`` queda afuera por posición en la pila, no por
    ``isinstance``: un middleware de usuario vive fuera de
    ``ExceptionMiddleware``, que ya convirtió cualquier ``HTTPException`` en
    respuesta antes de que el control vuelva acá — un 404/401/422 normal
    nunca llega a este ``except``.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            # scope["path"] nunca trae query string (el ASGI la separa en
            # scope["query_string"]), así que request_path queda libre de "?"
            # de forma estructural, sin filtrarla a mano.
            record_error(
                source="http",
                capture_kind="handler",
                exc=exc,
                request_method=scope.get("method"),
                request_path=scope.get("path"),
            )
            raise


app = FastAPI(
    title="OpenLivery API",
    description="API para gestionar agencias, clientes y agentes de IA.",
    version="0.3.0",
    lifespan=lifespan,
)
# Antes de CORSMiddleware a propósito (D2): add_middleware apila LIFO, así que
# registrar ErrorCaptureMiddleware primero lo deja por dentro de CORS y por
# fuera de ExceptionMiddleware — CORS sigue siendo la capa más externa incluso
# en un 500, y HTTPException queda excluido antes de llegar acá.
app.add_middleware(ErrorCaptureMiddleware)
app.add_middleware(
    CORSMiddleware,
    # El origen del frontend configurado (un dominio real en producción) más
    # cualquier puerto de localhost/127.0.0.1, así cambiar WEB_PORT nunca rompe
    # el desarrollo local.
    allow_origins=[settings.frontend_url],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
def liveness():
    """Liveness: responde mientras el proceso esté vivo y NO toca la base.

    Se llama ``liveness`` y no ``health`` porque este módulo importa el router
    ``health``: una función con ese nombre lo pisaba, y ``health.router``
    pasaba a buscar un atributo en una función. La ruta sigue siendo
    ``/health``, que es lo que golpea el healthcheck de docker-compose.
    """
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api")
app.include_router(agency.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(clients.router, prefix="/api")
app.include_router(departments.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(agent_tools.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(mobile.router, prefix="/api")
app.include_router(portal.router, prefix="/api")
app.include_router(whatsapp.router, prefix="/api")
app.include_router(whatsapp.internal_router, prefix="/api")
app.include_router(whatsapp_cloud.router, prefix="/api")
app.include_router(whatsapp_cloud_webhook.public_router, prefix="/api")
app.include_router(widget.router, prefix="/api")
app.include_router(domains.public_router, prefix="/api")

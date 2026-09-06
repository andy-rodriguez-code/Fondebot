"""Envío de mails salientes (por ahora, solo la invitación al portal).

Este módulo es un seam a propósito, igual que ``notifications.py``: un
proveedor es una función que recibe un :class:`Email` y lo entrega.
``EMAIL_PROVIDER`` selecciona uno; el default ``"none"`` no manda nada, y en
ese caso quien llama (el router) es responsable de devolver el link de
invitación en la respuesta para que la persona admin lo reenvíe a mano.

``"smtp"`` manda de verdad contra un servidor operado por quien despliega, vía
``smtplib`` de la librería estándar.

**Regla dura: ningún proveedor de este módulo se llama nunca desde adentro de
un ``async def``.** ``smtplib`` es bloqueante — abre un socket TCP y conversa
el protocolo SMTP línea por línea — así que llamarlo desde una corrutina
congela el event loop entero mientras dura esa conversación (potencialmente
varios segundos si el servidor SMTP es lento). Por eso ``Provider`` es
``Callable[[Email], None]``, sincrónico, no ``Awaitable``: el tipo mismo obliga
a que la única forma de invocarlo sea desde un hilo de threadpool (por ejemplo
``BackgroundTasks`` de FastAPI, que ya corre las tareas sync ahí). A diferencia
de ``notifications.py``, una entrega fallida acá NO se traga en silencio: una
notificación push perdida es recuperable (el mensaje ya está guardado), pero
una invitación perdida deja a la persona invitada sin ningún camino de
entrada. Quien llama a :func:`send_email` debe capturar la excepción y dejar
constancia (ver ``services/invitations.py`` y el wrapper de reintentos de
PR4), no asumir que "se mandó" solo porque no hubo excepción en el hilo
principal.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage as StdEmailMessage

from ..config import get_settings
from ..models import Client, Department

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 10


@dataclass
class Email:
    """Un mail listo para entregar: sin plantillas, sin adjuntos."""

    to: str
    subject: str
    body: str


# Sincrónico a propósito: ver el docstring del módulo.
Provider = Callable[[Email], None]

_PROVIDERS: dict[str, Provider] = {}


def register_provider(name: str, provider: Provider) -> None:
    """Habilita ``name`` como valor de ``EMAIL_PROVIDER``.

    Volver a registrar un nombre reemplaza al anterior, igual que en
    ``notifications.py``.
    """
    _PROVIDERS[name.strip().lower()] = provider


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def configured_provider() -> str:
    """El proveedor elegido por este deployment, o ``"none"``.

    Un nombre desconocido se trata como ``"none"`` y queda registrado en el
    log: un typo en la variable de entorno debe dejar el envío apagado, no
    tirar abajo una request que solo estaba creando una invitación.
    """
    name = (getattr(get_settings(), "email_provider", "") or "none").strip().lower()
    if name not in _PROVIDERS:
        if name != "none":
            logger.warning("EMAIL_PROVIDER=%r no está registrado; el envío de mails está apagado", name)
        return "none"
    return name


def email_enabled() -> bool:
    return configured_provider() != "none"


def _send_none(_email: Email) -> None:
    """No hace nada. La decisión de devolver el link en la respuesta la toma
    quien llama (el router), no este proveedor."""
    return None


def _send_smtp(email: Email) -> None:
    settings = get_settings()
    message = StdEmailMessage()
    message["Subject"] = email.subject
    message["From"] = settings.smtp_from
    message["To"] = email.to
    message.set_content(email.body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


register_provider("none", _send_none)
register_provider("smtp", _send_smtp)


def send_email(email: Email) -> None:
    """Entrega ``email`` con el proveedor configurado.

    A diferencia de ``notifications.notify_devices``, esto NO se traga
    excepciones: una invitación perdida no tiene otro rastro que este intento,
    así que quien llama debe decidir qué hacer con el fallo (ver D7 en el
    diseño — registrar ``delivery_error`` en la fila, no asumir éxito).
    """
    _PROVIDERS[configured_provider()](email)


def build_invitation_email(
    to: str, client: Client, department: Department | None, accept_url: str
) -> Email:
    """Compone el mail de invitación en español, con f-strings planas.

    ``to`` es un parámetro y no algo que quien llama asigne después: un
    :class:`Email` a medio armar, con el destinatario en blanco, se entrega
    igual sin fallar y no llega a ninguna parte. La firma no deja construir uno
    sin dirección.

    No pasa por ``apps/web/lib/i18n`` (es solo del navegador) ni imita el
    inglés hardcodeado de partes viejas de ``notifications.py``: sigue el
    mismo patrón que ``knowledge.py:build_system_prompt``, que también arma
    texto para una persona directamente en el backend.
    """
    department_name = department.name if department is not None else "el equipo"
    subject = f"Invitación al portal de {client.name}"
    body = (
        f"Hola,\n\n"
        f"Te invitaron a sumarte al portal de {client.name} como parte de "
        f"{department_name}.\n\n"
        f"Para activar tu cuenta y elegir tu contraseña, entrá a este link:\n"
        f"{accept_url}\n\n"
        f"Este link es de un solo uso y vence en 24 horas. Si no esperabas "
        f"esta invitación, podés ignorar este mensaje."
    )
    return Email(to=to, subject=subject, body=body)

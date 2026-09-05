"""Dependencias: el menú de entrada de WhatsApp y a quién le queda el caso.

Un cliente que tiene dependencias cargadas no atiende con un solo agente: al
abrirse la conversación se le ofrece al contacto el menú, y la dependencia que
elige se queda con el caso y lo contesta con su propio agente. Mientras no elija
atiende la dependencia de entrada (recepción).

El menú se arma una sola vez y se entrega distinto según el canal, porque los
botones tappables solo existen en la Cloud API: WhatsApp rompió los mensajes
interactivos para los clientes que hablan el protocolo de WhatsApp Web, así que
por Baileys va la misma lista numerada en texto plano. La coincidencia por
número funciona en los dos, y es la que usa quien escribe "2" en vez de tocar.
"""

from __future__ import annotations

import unicodedata
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Conversation, Department, Message, now_utc
from ..security import decrypt_secret
from .conversation_state import note_reply, record_activity
from .whatsapp import send_channel_message
from .whatsapp_cloud import MAX_BUTTONS, send_buttons, send_list

# Copia que ve el contacto en WhatsApp. Español neutro a propósito: es el
# idioma de quien atiende el negocio, igual que el prompt de sistema, y no pasa
# por el i18n de la interfaz porque no es interfaz.
MENU_INTRO = "¡Hola! ¿Con cuál dependencia deseas comunicarte?"
MENU_FOOTER = "Responde con el número de la opción."
MENU_LIST_BUTTON = "Ver dependencias"

PAYLOAD_PREFIX = "dept:"


def client_departments(db: Session, client_id: uuid.UUID) -> list[Department]:
    """Todas las dependencias del cliente, en el orden del menú."""
    return list(
        db.scalars(
            select(Department)
            .where(Department.client_id == client_id)
            .order_by(Department.position, Department.name)
        ).all()
    )


def menu_options(departments: list[Department]) -> list[Department]:
    """Las que se le ofrecen al contacto.

    Atender y estar en el menú son dos cosas distintas: una recepción que solo
    existe para contestar mientras el contacto elige se saca del menú con
    ``enabled=False`` y deja los botones para las dependencias de verdad.
    """
    return [department for department in departments if department.enabled]


def entry_department(departments: list[Department]) -> Department | None:
    """La de recepción, esté o no en el menú. Si nadie la marcó, la primera:
    es preferible que atienda alguien a que el contacto quede sin agente."""
    for department in departments:
        if department.is_entry:
            return department
    return departments[0] if departments else None


def payload_id(department: Department) -> str:
    """Lo que viaja como id del botón y vuelve en el webhook."""
    return f"{PAYLOAD_PREFIX}{department.slug}"


def _normalize(value: str) -> str:
    stripped = unicodedata.normalize("NFD", (value or "").strip().lower())
    return "".join(char for char in stripped if unicodedata.category(char) != "Mn")


def match_choice(departments: list[Department], *, text: str = "", payload: str = "") -> Department | None:
    """La dependencia que el contacto eligió, si eligió alguna.

    Tres formas, en orden de confianza: el id que devuelve un botón o una fila
    de lista, el número de posición del menú, y el nombre o el slug escritos
    completos. La coincidencia por texto es exacta a propósito — buscar la
    palabra adentro de la frase rutearía "no quiero saber nada con recaudo".
    """
    if payload and payload.startswith(PAYLOAD_PREFIX):
        wanted = payload[len(PAYLOAD_PREFIX) :]
        for department in departments:
            if department.slug == wanted:
                return department
        return None
    candidate = _normalize(text)
    if not candidate:
        return None
    if candidate.isdigit():
        position = int(candidate)
        if 1 <= position <= len(departments):
            return departments[position - 1]
        return None
    for department in departments:
        if candidate in (_normalize(department.name), _normalize(department.slug)):
            return department
    return None


def menu_text(departments: list[Department]) -> str:
    """El menú como texto. Es lo que se manda por Baileys y, en los dos canales,
    lo que queda guardado en el hilo para quien lo lea después desde el portal."""
    lines = [f"{index}. {department.name}" for index, department in enumerate(departments, start=1)]
    return "\n".join([MENU_INTRO, "", *lines, "", MENU_FOOTER])


async def _deliver_menu(db: Session, conversation: Conversation, channel, departments: list[Department]) -> str | None:
    """Entrega el menú por el canal de la conversación y devuelve el id externo."""
    if conversation.channel == "whatsapp_cloud":
        if not channel.encrypted_access_token or not channel.phone_number_id:
            raise HTTPException(status_code=409, detail="The WhatsApp API channel is not configured")
        access_token = decrypt_secret(channel.encrypted_access_token)
        if len(departments) <= MAX_BUTTONS:
            return await send_buttons(
                access_token,
                channel.phone_number_id,
                conversation.external_chat_id,
                MENU_INTRO,
                [(payload_id(item), item.name) for item in departments],
            )
        return await send_list(
            access_token,
            channel.phone_number_id,
            conversation.external_chat_id,
            MENU_INTRO,
            MENU_LIST_BUTTON,
            [(payload_id(item), item.name, item.description) for item in departments],
        )
    # Baileys y cualquier canal futuro sin mensajes interactivos.
    return await send_channel_message(db, conversation, menu_text(departments))


async def send_menu(db: Session, conversation: Conversation, channel, departments: list[Department]) -> bool:
    """Ofrece el menú una sola vez por conversación.

    Queda guardado en el hilo como un mensaje más, así quien abre la
    conversación en el portal ve lo mismo que vio el contacto. Si la entrega
    falla no se marca ``menu_sent_at``: el próximo mensaje lo vuelve a intentar,
    que es mejor que dejar al contacto sin opciones para siempre.
    """
    if not departments or conversation.menu_sent_at is not None or not conversation.external_chat_id:
        return False
    external_id = await _deliver_menu(db, conversation, channel, departments)
    conversation.menu_sent_at = now_utc()
    db.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=menu_text(departments),
            sender_type="system",
            external_message_id=external_id,
        )
    )
    note_reply(conversation)
    conversation.updated_at = now_utc()
    db.commit()
    return True


def route(db: Session, conversation: Conversation, department: Department, *, actor: str | None = None) -> bool:
    """Le pasa el caso a ``department`` y le cambia el agente que lo contesta.

    Devuelve si cambió algo, para que quien llama no escriba dos líneas de
    actividad cuando el contacto toca el mismo botón dos veces.
    """
    if conversation.department_id == department.id:
        return False
    conversation.department_id = department.id
    conversation.agent_id = department.agent_id
    # El caso cambia de equipo. Quien lo tuviera asignado ya no es de esta
    # dependencia, así que deja de ser suyo y vuelve a la cola.
    if conversation.assignee_id is not None:
        conversation.assignee_id = None
        conversation.assigned_at = None
    record_activity(db, conversation, "routed", actor=actor, details={"department": department.name})
    conversation.updated_at = now_utc()
    return True

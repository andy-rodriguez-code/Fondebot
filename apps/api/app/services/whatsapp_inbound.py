"""Pipeline de entrada de WhatsApp, agnóstico del canal.

Lo comparten el endpoint del bridge de Baileys y el webhook de la Cloud API:
deduplicar por id externo de mensaje, encontrar o crear la conversación,
resolver la media a texto, guardar el mensaje del visitante y producir la
respuesta de la IA, salvo que una persona haya tomado la conversación. Entregar
la respuesta es responsabilidad de quien llama.
"""

import asyncio
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import new_session
from .contacts import display_name, phone_from_chat_id, previous_conversation_recap, rename_conversations, resolve_contact
from .conversation_state import exchanged_only, note_inbound, note_reply
from .departments import client_departments, entry_department, match_choice, menu_options, route, send_menu
from ..models import Agent, Conversation, Message, now_utc
from ..security import decrypt_secret
from .attachments import llm_text, store_attachment
from .knowledge import build_system_prompt, retrieve_knowledge
from .media import describe_image, transcribe_audio
from .notifications import notify_needs_human
from .providers import resolve_agent_credentials, resolve_provider_credentials
from .realtime import publish as publish_change
from .tools import run_completion
from .usage import record_usage
from .whatsapp import send_channel_message
from .whatsapp_cloud import mark_read_with_typing, send_reaction
from .whatsapp_format import parse_reply_directives


@dataclass
class InboundMessage:
    external_message_id: str
    external_chat_id: str
    sender_name: str | None = None
    text: str = ""
    media_kind: str | None = None
    media_bytes: bytes | None = None
    media_mime: str | None = None
    # El id que devuelve un botón o una fila de lista de la Cloud API. Vale más
    # que el texto para saber qué eligió el contacto: es lo que mandamos
    # nosotros, no lo que se ve en pantalla.
    interactive_payload: str | None = None


@dataclass
class InboundResult:
    accepted: bool
    reply: str | None = None
    conversation_id: uuid.UUID | None = None
    mode: str | None = None
    outbound_message_id: uuid.UUID | None = None
    # Id externo del mensaje del visitante que cita la respuesta (responder deslizando).
    quote_external_id: str | None = None


def _answering_agent(conversation: Conversation, channel) -> Agent:
    """El agente que contesta esta conversación.

    Con dependencias es el de la dependencia dueña del caso, que cambia cuando
    el contacto elige otra. Sin dependencias sigue siendo el del canal, tal como
    era antes: leerlo del canal es lo que hace que cambiarle el agente al canal
    afecte también a las conversaciones que ya estaban abiertas.
    """
    return conversation.agent if conversation.department_id else channel.agent


def _media_placeholder(kind: str) -> str:
    if kind == "image":
        return "[El cliente envió una imagen]"
    if kind == "audio":
        return "[El cliente envió una nota de voz]"
    if kind == "video":
        return "[El cliente envió un video]"
    return "[El cliente envió un archivo]"


async def resolve_inbound_content(db: Session, agent: Agent, inbound: InboundMessage) -> tuple[str, str]:
    """Resuelve qué guardar para el mensaje como ``(display, llm)``: el texto
    visible del chat (el epígrafe — el archivo de media en sí queda como
    adjunto) y el texto que ve el LLM, transcribiendo o describiendo la media
    cuando las capacidades del agente lo permiten. Con la mejor intención
    posible: el texto para el LLM cae a un marcador si algo falla."""
    text = (inbound.text or "").strip()
    if not inbound.media_kind:
        return text, text
    if not inbound.media_bytes:
        return text, text or _media_placeholder(inbound.media_kind)
    enabled = (inbound.media_kind == "image" and agent.image_enabled) or (
        inbound.media_kind == "audio" and agent.audio_enabled
    )
    credentials = resolve_provider_credentials(db, agent.agency_id, "openai")
    if not enabled or not credentials:
        return text, text or _media_placeholder(inbound.media_kind)
    try:
        data = inbound.media_bytes
        base_url, api_key = credentials
        if inbound.media_kind == "image":
            model = agent.image_model.strip() or agent.model.strip()
            instruction = (
                "Describe con detalle el contenido de esta imagen para que un asistente pueda responder al cliente."
                + (f" El cliente escribió: {text}" if text else "")
            )
            description = await describe_image(base_url, api_key, model, data, inbound.media_mime or "image/jpeg", instruction)
            return text, (f"{text}\n\n" if text else "") + f"[Imagen recibida] {description}"
        model = agent.audio_model.strip() or "whisper-1"
        transcript = await transcribe_audio(base_url, api_key, model, data, "audio.ogg", inbound.media_mime or "audio/ogg")
        return text, (f"{text}\n\n" if text else "") + (transcript or _media_placeholder("audio"))
    except (HTTPException, ValueError):
        return text, text or _media_placeholder(inbound.media_kind)


async def process_inbound(
    db: Session,
    channel,
    inbound: InboundMessage,
    *,
    conversation_channel: str,
    channel_fk_field: str,
) -> InboundResult:
    """Corre el pipeline compartido para un mensaje entrante.

    ``channel`` es un WhatsAppChannel o un WhatsAppCloudChannel; ambos exponen
    los mismos campos que se usan acá. ``conversation_channel`` y
    ``channel_fk_field`` eligen la etiqueta de canal de la Conversation y la
    columna de FK para quien llama.
    """
    fk_column = getattr(Conversation, channel_fk_field)

    existing = db.scalar(
        select(Message)
        .join(Conversation)
        .where(
            fk_column == channel.id,
            Message.external_message_id == inbound.external_message_id,
        )
    )
    if existing:
        return InboundResult(accepted=False, conversation_id=existing.conversation_id)

    # Un mensaje se suma a la conversación abierta de ese chat; una vez que esa
    # se resuelve, el siguiente mensaje arranca un caso nuevo, así que un mismo
    # id de chat puede contener muchas.
    conversation = db.scalar(
        select(Conversation)
        .where(
            fk_column == channel.id,
            Conversation.external_chat_id == inbound.external_chat_id,
            Conversation.status != "resolved",
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    departments = client_departments(db, channel.client_id)
    entry = entry_department(departments)
    # Lo que se ofrece puede ser menos que lo que existe: la recepción suele
    # quedar fuera del menú, porque es donde el contacto ya está parado.
    options = menu_options(departments)

    if not conversation:
        phone = phone_from_chat_id(inbound.external_chat_id)
        contact = resolve_contact(db, channel.client_id, phone=phone, name=inbound.sender_name) if phone else None
        if contact:
            title = display_name(contact)[:240]
        else:
            title = (inbound.sender_name or inbound.external_chat_id.split("@")[0])[:240]
        conversation = Conversation(
            agency_id=channel.agency_id,
            client_id=channel.client_id,
            # Un cliente con dependencias arranca en recepción, no en el agente
            # del canal: alguien tiene que atender mientras el contacto elige.
            agent_id=entry.agent_id if entry else channel.agent_id,
            department_id=entry.id if entry else None,
            external_chat_id=inbound.external_chat_id,
            contact_name=inbound.sender_name,
            contact_id=contact.id if contact else None,
            title=title,
            channel=conversation_channel,
            **{channel_fk_field: channel.id},
        )
        db.add(conversation)
        db.flush()
    elif inbound.sender_name:
        conversation.contact_name = inbound.sender_name
        contact = conversation.contact
        if contact and not contact.name.strip():
            contact.name = inbound.sender_name.strip()[:180]
            rename_conversations(db, contact)

    display_content, llm_content = await resolve_inbound_content(db, _answering_agent(conversation, channel), inbound)
    visitor_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=display_content,
        llm_content=llm_content if llm_content != display_content else None,
        sender_type="visitor",
        sender_name=inbound.sender_name or "WhatsApp contact",
        external_message_id=inbound.external_message_id,
    )
    conversation.updated_at = now_utc()
    note_inbound(db, conversation)
    db.add(visitor_message)
    if inbound.media_kind and inbound.media_bytes:
        db.flush()
        store_attachment(
            db,
            visitor_message,
            data=inbound.media_bytes,
            mime=inbound.media_mime or ("image/jpeg" if inbound.media_kind == "image" else "audio/ogg"),
            kind=inbound.media_kind,
        )
    db.commit()
    # El mensaje del visitante ya está guardado. Este es el aviso que de verdad
    # importa: es lo que hace aparecer algo nuevo en la pantalla de quien
    # atiende, sin esperar al refresco.
    publish_change(
        client_id=conversation.client_id,
        department_id=conversation.department_id,
        conversation_id=conversation.id,
    )
    if conversation.mode == "human":
        # Alguien tomó esta conversación, así que no va a responder nadie salvo
        # que una persona la vea. Este es el momento en que tiene que sonar un
        # teléfono.
        await notify_needs_human(db, conversation, display_content or llm_content)
        return InboundResult(accepted=True, conversation_id=conversation.id, mode="human")

    if options:
        # El texto solo cuenta como elección mientras el contacto sigue en
        # recepción. Después, un "2" es parte de la charla con su dependencia y
        # no un cambio de área. El botón vale siempre: ahí la intención es
        # explícita, y es la forma de volver al menú.
        in_entry = entry is not None and conversation.department_id == entry.id
        chosen = match_choice(
            options,
            text=display_content if in_entry else "",
            payload=inbound.interactive_payload or "",
        )
        if chosen and route(db, conversation, chosen, actor=inbound.sender_name):
            db.commit()
            # Segundo aviso, y no es redundante: el de arriba salió con la
            # dependencia de antes, porque el ruteo pasa recién acá. Sin este,
            # la dependencia que acaba de quedarse con el caso no se entera de
            # que le llegó hasta el refresco de respaldo.
            publish_change(
                client_id=conversation.client_id,
                department_id=conversation.department_id,
                conversation_id=conversation.id,
            )
        elif await send_menu(db, conversation, channel, options):
            # El menú es la respuesta de este turno. Nadie más contesta hasta
            # que el contacto elija, o escriba algo que atiende recepción.
            return InboundResult(accepted=True, conversation_id=conversation.id, mode="ai")

    if get_settings().reply_debounce_seconds > 0:
        schedule_debounced_reply(conversation.id)
        return InboundResult(accepted=True, conversation_id=conversation.id, mode="ai")

    await _signal_read_and_typing(channel, conversation, inbound.external_message_id)
    return await _reply_with_ai(db, channel, conversation, llm_content)


# Se inyecta en el prompt de sistema de las conversaciones por Cloud API (queda
# en el idioma de la clientela, como el resto del andamiaje que mira al LLM). El
# modelo decide SI y CUÁNDO, con criterio conversacional; el código solo ejecuta.
WHATSAPP_GESTURE_RULES = (
    "GESTOS DE WHATSAPP (opcionales; úsalos con moderación y criterio, como lo haría una persona):\n"
    "- Cuando el último mensaje del cliente no necesite una respuesta en texto y un gesto baste — en cualquier "
    "idioma: un agradecimiento, una despedida, una confirmación breve, un elogio, algo gracioso, un emoji —, "
    "puedes responder solo con una reacción: escribe únicamente la línea [react: EMOJI], eligiendo el emoji que "
    "mejor exprese tu reacción a ese mensaje y su tono (👍 ❤️ 😂 🙌 🎉 o cualquier otro). También puedes poner esa "
    "línea primero y añadir texto debajo.\n"
    "- La mayoría de las respuestas no necesitan ningún gesto. Nunca reacciones dos veces seguidas."
)

WHATSAPP_QUOTE_RULE = (
    "- El cliente envió varios mensajes seguidos, numerados abajo. Si tu respuesta se centra en uno en "
    "particular, puedes comenzar con la línea [quote: N] para responder citándolo (como al deslizar un "
    "mensaje en WhatsApp). Cítalo solo cuando aclare a qué respondes:\n{listing}"
)


def _trailing_visitor_burst(history: list[Message]) -> list[Message]:
    """Los mensajes consecutivos del visitante al final del historial: la ráfaga
    que el agente está por contestar, del más viejo al más nuevo."""
    burst: list[Message] = []
    for item in reversed(history):
        if item.role != "user":
            break
        burst.append(item)
    return list(reversed(burst))


def _gesture_rules(burst: list[Message]) -> str:
    rules = WHATSAPP_GESTURE_RULES
    if len(burst) > 1:
        listing = "\n".join(f"[{index}] {llm_text(item)[:160]}" for index, item in enumerate(burst, start=1))
        rules += "\n" + WHATSAPP_QUOTE_RULE.format(listing=listing)
    return rules


async def _apply_gestures(
    db: Session, channel, conversation: Conversation, completion_text: str, burst: list[Message]
) -> tuple[str, uuid.UUID | None, str | None]:
    """Ejecuta las directivas de gesto que encabezan la respuesta (react/quote) y
    las saca del texto. Devuelve ``(clean_text, quoted_message_id, quote_external_id)``."""
    clean_text, emoji, quote_index = parse_reply_directives(completion_text)
    quoted_id: uuid.UUID | None = None
    quote_external: str | None = None
    if not channel.encrypted_access_token or not channel.phone_number_id:
        return clean_text, None, None
    if emoji and burst and burst[-1].external_message_id:
        target = burst[-1]
        await send_reaction(
            decrypt_secret(channel.encrypted_access_token),
            channel.phone_number_id,
            conversation.external_chat_id,
            target.external_message_id,
            emoji,
        )
        target.reaction = emoji
    if quote_index and 1 <= quote_index <= len(burst) and burst[quote_index - 1].external_message_id:
        quoted = burst[quote_index - 1]
        quoted_id = quoted.id
        quote_external = quoted.external_message_id
    return clean_text, quoted_id, quote_external


async def _signal_read_and_typing(channel, conversation: Conversation, message_external_id: str | None) -> None:
    """Marca con el tilde azul la ráfaga del visitante y muestra "escribiendo..."
    mientras se genera la respuesta de la IA: el momento en que se cierra la
    ventana de silencio es cuando una persona habría leído los mensajes. Solo
    para Cloud API; el bridge todavía no tiene esa señal."""
    if conversation.channel != "whatsapp_cloud" or not message_external_id:
        return
    if not channel.encrypted_access_token or not channel.phone_number_id:
        return
    await mark_read_with_typing(
        decrypt_secret(channel.encrypted_access_token), channel.phone_number_id, message_external_id
    )


async def _reply_with_ai(db: Session, channel, conversation: Conversation, retrieval_query: str) -> InboundResult:
    """Genera y guarda la respuesta de la IA para el historial actual de la conversación.

    ``retrieval_query`` maneja la recuperación de conocimiento: el texto del
    mensaje que disparó todo en el camino síncrono, o la ráfaga completa del
    visitante cuando hay debounce.
    """
    agent = _answering_agent(conversation, channel)
    credentials = resolve_agent_credentials(db, agent)
    if not agent.is_active or not credentials or not agent.model.strip():
        channel.last_error = "A message was received, but the assigned agent is not ready (model or provider key missing)."
        channel.updated_at = now_utc()
        db.commit()
        return InboundResult(accepted=True, conversation_id=conversation.id, mode="ai")

    knowledge = await retrieve_knowledge(db, agent, retrieval_query)
    db.refresh(conversation)
    history = db.scalars(
        exchanged_only(select(Message).where(Message.conversation_id == conversation.id))
        .order_by(Message.created_at.desc())
        .limit(agent.memory_limit)
    ).all()
    history = list(reversed(history))
    burst = _trailing_visitor_burst(history)
    system_content = build_system_prompt(agent, knowledge.text)
    recap = previous_conversation_recap(db, conversation)
    if recap:
        system_content += "\n\n" + recap
    if conversation.channel == "whatsapp_cloud":
        system_content += "\n\n" + _gesture_rules(burst)
    messages = [
        {"role": "system", "content": system_content},
        *[{"role": item.role, "content": llm_text(item)} for item in history],
    ]
    base_url, api_key = credentials
    try:
        completion = await run_completion(
            db,
            agent,
            base_url,
            api_key,
            messages,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
        )
    except Exception as exc:
        channel.last_error = f"Message received, but the agent could not reply: {str(exc)[:400]}"
        channel.updated_at = now_utc()
        db.commit()
        return InboundResult(accepted=True, conversation_id=conversation.id, mode="ai")

    reply_text = completion.text
    quoted_message_id: uuid.UUID | None = None
    quote_external_id: str | None = None
    if conversation.channel == "whatsapp_cloud":
        reply_text, quoted_message_id, quote_external_id = await _apply_gestures(
            db, channel, conversation, completion.text, burst
        )

    outbound = None
    if reply_text:
        note_reply(conversation)
        outbound = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=reply_text,
            sources=knowledge.sources,
            tool_calls=completion.tool_calls,
            sender_type="ai",
            sender_name=agent.name,
            quoted_message_id=quoted_message_id,
        )
        db.add(outbound)
    record_usage(db, agent.agency_id, agent.id, agent.provider, agent.model.strip(), completion)
    conversation.updated_at = now_utc()
    channel.last_error = None
    db.commit()
    return InboundResult(
        accepted=True,
        reply=reply_text or None,
        conversation_id=conversation.id,
        mode="ai",
        outbound_message_id=outbound.id if outbound else None,
        quote_external_id=quote_external_id,
    )


_pending_replies: dict[uuid.UUID, "asyncio.Task[None]"] = {}


def schedule_debounced_reply(conversation_id: uuid.UUID) -> None:
    """(Re)inicia el temporizador de ventana de silencio de la conversación.

    Cada mensaje entrante cancela el temporizador anterior, así que la respuesta
    se dispara solo cuando pasa la ventana sin un mensaje nuevo del visitante, y
    contesta toda la ráfaga con una sola respuesta armada desde el historial
    guardado. Los temporizadores viven en el proceso; una revalidación contra la
    base cuando el temporizador se dispara hace que uno viejo sea inofensivo.
    """
    previous = _pending_replies.pop(conversation_id, None)
    if previous is not None and not previous.done():
        previous.cancel()
    task = asyncio.get_running_loop().create_task(_debounced_reply(conversation_id))
    _pending_replies[conversation_id] = task

    def _cleanup(finished: "asyncio.Task[None]") -> None:
        if _pending_replies.get(conversation_id) is finished:
            _pending_replies.pop(conversation_id, None)

    task.add_done_callback(_cleanup)


async def _debounced_reply(conversation_id: uuid.UUID) -> None:
    await asyncio.sleep(get_settings().reply_debounce_seconds)
    db = new_session()
    try:
        conversation = db.get(Conversation, conversation_id)
        if not conversation or conversation.mode == "human":
            return
        channel = conversation.whatsapp_channel or conversation.whatsapp_cloud_channel
        if not channel:
            return
        last = db.scalar(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.kind == "message")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        if not last or last.role != "user":
            # Ya respondió un temporizador más nuevo, otro worker, o una persona.
            return
        history = db.scalars(
            exchanged_only(select(Message).where(Message.conversation_id == conversation_id))
            .order_by(Message.created_at.desc())
            .limit(_answering_agent(conversation, channel).memory_limit)
        ).all()
        burst: list[str] = []
        for item in history:
            if item.role != "user":
                break
            burst.append(llm_text(item))
        await _signal_read_and_typing(channel, conversation, last.external_message_id)
        try:
            result = await _reply_with_ai(db, channel, conversation, "\n".join(reversed(burst)))
        except Exception as exc:
            channel.last_error = f"Message received, but the agent could not reply: {str(exc)[:400]}"
            channel.updated_at = now_utc()
            db.commit()
            return
        if not result.reply:
            return
        try:
            external_id = await send_channel_message(
                db, conversation, result.reply, quoted_external_id=result.quote_external_id
            )
        except HTTPException as exc:
            channel.last_error = f"The reply could not be sent: {exc.detail}"
            channel.updated_at = now_utc()
            db.commit()
            return
        if external_id and result.outbound_message_id:
            outbound = db.get(Message, result.outbound_message_id)
            if outbound:
                outbound.external_message_id = external_id
                db.commit()
        publish_change(
            client_id=conversation.client_id,
            department_id=conversation.department_id,
            conversation_id=conversation.id,
        )
    finally:
        db.close()

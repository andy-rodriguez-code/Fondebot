"""La ventana de retencion de los binarios de mensajes.

``message_attachments`` es la unica tabla que crece sin techo con el uso: cada
imagen y cada nota de voz que manda un contacto queda entera. Lo que se prueba
aca es que la ventana borra lo viejo, respeta lo nuevo, y que apagada no toca
nada — que es como llega a quien ya tiene el producto instalado.
"""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Agency, Agent, Client, Conversation, Message, MessageAttachment, now_utc
from app.services.attachments import purge_attachments


def _attachment(db, *, age_days: int) -> uuid.UUID:
    """Un adjunto con la edad pedida, con toda la cadena que exige el esquema."""
    suffix = uuid.uuid4().hex[:8]
    agency = Agency(name="Fondo", slug=f"fondo-{suffix}")
    db.add(agency)
    db.flush()
    client = Client(agency_id=agency.id, name="Cooperativa", portal_slug=f"coop-{suffix}")
    db.add(client)
    db.flush()
    agent = Agent(agency_id=agency.id, client_id=client.id, name="Asistente")
    db.add(agent)
    db.flush()
    conversation = Conversation(agency_id=agency.id, client_id=client.id, agent_id=agent.id, title="Caso")
    db.add(conversation)
    db.flush()
    message = Message(conversation_id=conversation.id, role="user", content="mira esto")
    db.add(message)
    db.flush()
    attachment = MessageAttachment(
        message_id=message.id,
        kind="image",
        mime="image/jpeg",
        filename="foto.jpg",
        size_bytes=3,
        data=b"jpg",
        created_at=now_utc() - timedelta(days=age_days),
    )
    db.add(attachment)
    db.commit()
    return attachment.id


def _ids(db) -> set:
    return set(db.scalars(select(MessageAttachment.id)).all())


def test_the_window_removes_what_is_past_it():
    with SessionLocal() as db_session:
        old = _attachment(db_session, age_days=40)
        recent = _attachment(db_session, age_days=3)

        assert purge_attachments(db_session, days=30) == 1
        assert _ids(db_session) == {recent}
        assert old not in _ids(db_session)


def test_the_edge_of_the_window_is_kept():
    with SessionLocal() as db_session:
        """Justo dentro de la ventana se queda: el borde no se redondea hacia afuera."""
        inside = _attachment(db_session, age_days=29)
        assert purge_attachments(db_session, days=30) == 0
        assert _ids(db_session) == {inside}


def test_disabled_deletes_nothing():
    with SessionLocal() as db_session:
        """El valor por defecto, y el que importa mas.

        Actualizar la aplicacion no puede empezar a borrarle datos a alguien que no
        lo pidio, por muy viejos que sean.
        """
        ancient = _attachment(db_session, age_days=3650)
        assert purge_attachments(db_session, days=0) == 0
        assert purge_attachments(db_session, days=-1) == 0
        assert _ids(db_session) == {ancient}


def test_the_message_survives_its_attachment():
    with SessionLocal() as db_session:
        """Se va el binario, no la conversacion.

        Quien lea el caso despues sigue viendo que hubo un mensaje y su texto; lo
        unico que falta es el archivo original.
        """
        _attachment(db_session, age_days=40)
        purge_attachments(db_session, days=30)

        messages = db_session.scalars(select(Message)).all()
        assert len(messages) == 1
        assert messages[0].content == "mira esto"

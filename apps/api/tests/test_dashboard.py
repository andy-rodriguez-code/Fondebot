"""Las métricas del panel.

Este router no tenía ninguna prueba. Los números que muestra se leen para
decidir, así que uno mal contado es peor que uno ausente: nadie audita una
cifra que parece razonable.
"""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Client, Conversation, Message, now_utc


def _make_client(client: TestClient, name: str = "Fondo") -> dict:
    return client.post(
        "/api/clients",
        json={"name": name, "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()


def _make_agent(client: TestClient, client_id: str, name: str = "Agente") -> dict:
    client.put("/api/providers/openai", json={"api_key": "secret"})
    return client.post(
        "/api/agents",
        json={
            "client_id": client_id,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "name": name,
            "description": "",
            "instructions": "",
            "personality": "",
            "is_active": True,
        },
    ).json()


def _make_department(client: TestClient, client_id: str, agent_id: str, name: str) -> dict:
    created = client.post(
        f"/api/clients/{client_id}/departments", json={"name": name, "agent_id": agent_id}
    )
    assert created.status_code == 201, created.text
    return created.json()


def _seed_conversation(
    *, client_id: str, agent_id: str, department_id: str | None = None, first_reply_after: int | None = None
) -> uuid.UUID:
    """Inserta una conversación directo: lo que se prueba es el conteo, no cómo
    nace una conversación."""
    with SessionLocal() as db:
        row = db.get(Client, uuid.UUID(client_id))
        opened = now_utc()
        conversation = Conversation(
            agency_id=row.agency_id,
            client_id=row.id,
            agent_id=uuid.UUID(agent_id),
            department_id=uuid.UUID(department_id) if department_id else None,
            title="Caso",
            channel="whatsapp_cloud",
            created_at=opened,
            first_reply_at=opened + timedelta(seconds=first_reply_after) if first_reply_after is not None else None,
        )
        db.add(conversation)
        db.commit()
        return conversation.id


def _seed_messages(conversation_id: uuid.UUID, *, received: int, sent: int, activity: int) -> None:
    with SessionLocal() as db:
        for _ in range(received):
            db.add(Message(conversation_id=conversation_id, role="user", content="hola", sender_type="visitor"))
        for _ in range(sent):
            db.add(Message(conversation_id=conversation_id, role="assistant", content="hola", sender_type="ai"))
        for _ in range(activity):
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role="system",
                    kind="activity",
                    activity={"event": "resolved"},
                    content="alguien resolvió la conversación",
                    sender_type="system",
                )
            )
        db.commit()


def test_messages_are_split_and_activity_rows_are_not_messages(authenticated_client: TestClient):
    """Las filas de actividad viven en la misma tabla que los mensajes.

    Antes entraban en el total, que venía inflado: "alguien resolvió la
    conversación" no lo mandó ni lo recibió nadie.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    conversation = _seed_conversation(client_id=customer["id"], agent_id=agent["id"])
    _seed_messages(conversation, received=3, sent=2, activity=4)

    metrics = client.get("/api/dashboard/metrics").json()

    assert metrics["messages_received"] == 3
    assert metrics["messages_sent"] == 2
    # Y el total sigue siendo la suma de los dos, no de las nueve filas.
    assert metrics["messages"] == 5


def test_a_human_reply_counts_as_sent_just_like_the_ai(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    conversation = _seed_conversation(client_id=customer["id"], agent_id=agent["id"])
    with SessionLocal() as db:
        db.add(Message(conversation_id=conversation, role="assistant", content="x", sender_type="human"))
        db.add(Message(conversation_id=conversation, role="user", content="x", sender_type="visitor"))
        db.commit()

    metrics = client.get("/api/dashboard/metrics").json()

    # Lo que importa para quien mira el número es hacia dónde fue, no quién lo
    # escribió.
    assert metrics["messages_sent"] == 1
    assert metrics["messages_received"] == 1


def test_departments_are_counted_and_an_idle_one_still_shows(authenticated_client: TestClient):
    """Una dependencia sin conversaciones aparece en cero.

    Es la que más hay que ver: que no le esté entrando nada es información, y
    un INNER JOIN la habría hecho desaparecer justo cuando importa.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    busy = _make_department(client, customer["id"], agent["id"], "Tesorería")
    _make_department(client, customer["id"], agent["id"], "Contabilidad")
    _seed_conversation(client_id=customer["id"], agent_id=agent["id"], department_id=busy["id"])

    assert client.get("/api/dashboard").json()["departments"] == 2

    by_department = client.get("/api/dashboard/metrics").json()["by_department"]
    assert {row["name"]: row["conversations"] for row in by_department} == {
        "Tesorería": 1,
        "Contabilidad": 0,
    }


def test_the_first_reply_time_is_a_median_not_an_average(authenticated_client: TestClient):
    """Con 10, 20 y 600 segundos, el promedio da 210 y la mediana 20.

    Una conversación que quedó abandonada un fin de semana no debería mover el
    número que dice cuánto espera la gente habitualmente.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    for seconds in (10, 20, 600):
        _seed_conversation(client_id=customer["id"], agent_id=agent["id"], first_reply_after=seconds)

    assert client.get("/api/dashboard/metrics").json()["median_first_reply_seconds"] == 20


def test_no_answered_conversation_reports_nothing_rather_than_zero(authenticated_client: TestClient):
    """Cero segundos de espera sería mentir hacia el lado bueno."""
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    _seed_conversation(client_id=customer["id"], agent_id=agent["id"], first_reply_after=None)

    assert client.get("/api/dashboard/metrics").json()["median_first_reply_seconds"] is None


def test_the_window_leaves_out_what_is_older_than_it(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    conversation = _seed_conversation(client_id=customer["id"], agent_id=agent["id"])
    _seed_messages(conversation, received=1, sent=1, activity=0)
    with SessionLocal() as db:
        for row in db.query(Message).all():
            row.created_at = now_utc() - timedelta(days=40)
        db.commit()

    assert client.get("/api/dashboard/metrics?days=7").json()["messages"] == 0
    assert client.get("/api/dashboard/metrics?days=90").json()["messages"] == 2

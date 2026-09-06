"""Pruebas de los puntos de captura cableados en la Slice 1b: middleware ASGI,
callback de debounce, barrido de auto-resolve y barrido de purga.

Para cada una: qué se rompe si la propiedad que cubre retrocede. Ver
sdd/site-health-and-error-tracking/design (D2, D3, D5, D7) para el porqué de
cada guarda.
"""

import asyncio
import contextlib
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main as main_module
from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import Conversation, ErrorEvent, WhatsAppChannel
from app.services import whatsapp_inbound as inbound_service


# --- ErrorCaptureMiddleware (2.1 / 2.2) --------------------------------------


def _install_boom_route():
    async def _boom():
        raise RuntimeError("boom del test")

    app.add_api_route("/api/__test_boom__", _boom, methods=["GET"])
    return app.router.routes[-1]


@pytest.fixture
def lenient_client(client: TestClient):
    """Un TestClient que deja llegar la respuesta del servidor sin relanzar la
    excepción a la prueba misma, tal como la vería un navegador real.

    Reusa las ``dependency_overrides`` que ya dejó armadas el fixture
    ``client`` (mismo ``app``) y NO entra como context manager: entrar de
    nuevo correría el lifespan una segunda vez, duplicando las tareas en
    segundo plano que el ``client`` original ya tiene corriendo.
    """
    route = _install_boom_route()
    lenient = TestClient(app, raise_server_exceptions=False)
    try:
        yield lenient
    finally:
        lenient.close()
        app.router.routes.remove(route)


def test_an_unhandled_route_exception_is_recorded_and_the_response_is_unchanged(lenient_client):
    response = lenient_client.get("/api/__test_boom__?token=abc123")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert row.capture_kind == "handler"
        assert row.source == "http"
        assert row.exception_type == "RuntimeError"
        assert row.request_path == "/api/__test_boom__"
        assert "?" not in row.request_path


def test_normal_http_errors_are_not_recorded(lenient_client):
    unauthorized = lenient_client.get("/api/conversations/inbox")
    not_found = lenient_client.get("/api/this-route-does-not-exist")

    assert unauthorized.status_code == 401
    assert not_found.status_code == 404

    with SessionLocal() as db:
        assert db.query(ErrorEvent).count() == 0


# --- Callback de debounce (2.4 / 2.6) ---------------------------------------


def test_a_cancelled_debounce_timer_records_nothing(monkeypatch):
    conversation_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    monkeypatch.setattr(get_settings(), "reply_debounce_seconds", 0.2)

    async def scenario():
        # La segunda llamada cancela el temporizador de la primera: es el
        # tráfico sano de cada mensaje nuevo del visitante, no una falla.
        inbound_service.schedule_debounced_reply(conversation_id, agency_id)
        await asyncio.sleep(0.05)
        inbound_service.schedule_debounced_reply(conversation_id, agency_id)
        await asyncio.sleep(0.5)

    asyncio.run(scenario())

    with SessionLocal() as db:
        assert db.query(ErrorEvent).count() == 0


def _setup_channel(client: TestClient) -> None:
    customer = client.post(
        "/api/clients",
        json={
            "name": "Sol Store",
            "industry": "Retail",
            "description": "",
            "general_context": "Open Monday through Saturday.",
            "is_active": True,
        },
    ).json()
    client.put("/api/providers/openai", json={"api_key": "secret"})
    agent = client.post(
        "/api/agents",
        json={
            "client_id": customer["id"],
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "name": "Sol Advisor",
            "description": "",
            "instructions": "Help the customers.",
            "personality": "Friendly",
            "is_active": True,
        },
    ).json()
    assert client.put(
        f"/api/whatsapp/channels/{customer['id']}", json={"agent_id": agent["id"]}
    ).status_code == 200


def _inbound(external_message_id: str, text: str) -> inbound_service.InboundMessage:
    return inbound_service.InboundMessage(
        external_message_id=external_message_id,
        external_chat_id="573001112233@s.whatsapp.net",
        sender_name="Cliente",
        text=text,
    )


async def _process(db, channel, message: inbound_service.InboundMessage):
    return await inbound_service.process_inbound(
        db,
        channel,
        message,
        conversation_channel="whatsapp",
        channel_fk_field="whatsapp_channel_id",
    )


def test_a_failure_outside_the_inner_try_blocks_is_recorded_with_its_agency(
    authenticated_client: TestClient, monkeypatch
):
    _setup_channel(authenticated_client)
    monkeypatch.setattr(get_settings(), "reply_debounce_seconds", 0.15)
    monkeypatch.setattr(
        inbound_service,
        "_signal_read_and_typing",
        AsyncMock(side_effect=RuntimeError("no llega")),
    )

    db = SessionLocal()
    try:
        channel = db.scalar(select(WhatsAppChannel))

        async def scenario():
            await _process(db, channel, _inbound("wa-1", "hola"))
            await asyncio.sleep(0.5)

        asyncio.run(scenario())

        conversation = db.scalar(select(Conversation))
        row = db.query(ErrorEvent).one()
        assert row.capture_kind == "task_callback"
        assert row.source == "whatsapp.debounced_reply"
        assert row.agency_id == conversation.agency_id
        assert row.subject_ref == f"conversation:{conversation.id}"
    finally:
        db.close()


# --- Barrido de auto-resolve (2.8) ------------------------------------------


def test_a_failing_auto_resolve_pass_is_recorded_and_the_loop_continues(monkeypatch):
    monkeypatch.setattr(main_module, "AUTO_RESOLVE_SWEEP_SECONDS", 0.05)
    calls = {"count": 0}

    def _flaky(db, *, hours):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("fallo simulado")
        return 0

    monkeypatch.setattr(main_module, "resolve_idle_ai_conversations", _flaky)

    async def scenario():
        task = asyncio.create_task(main_module._auto_resolve_loop())
        await asyncio.sleep(0.25)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    # Sigue corriendo después del fallo: no murió en la primera pasada.
    assert calls["count"] >= 2
    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert row.capture_kind == "explicit"
        assert row.source == "conversations.auto_resolve"


# --- Barrido de purga (2.10) -------------------------------------------------


def test_a_failed_purge_sweep_records_exactly_one_row(monkeypatch):
    monkeypatch.setattr(main_module, "ERROR_LOG_SWEEP_SECONDS", 0.05)

    def _always_fails(db, *, days, max_rows):
        raise RuntimeError("fallo de purga simulado")

    monkeypatch.setattr(main_module, "purge_error_events", _always_fails)

    async def scenario():
        task = asyncio.create_task(main_module._error_log_purge_loop())
        # Alcanza para UNA pasada (a los ~0.05s) y se cancela antes de que
        # empiece la siguiente (a los ~0.10s): así la prueba puede afirmar
        # "exactamente una fila", no "como mucho una por pasada".
        await asyncio.sleep(0.08)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    with SessionLocal() as db:
        row = db.query(ErrorEvent).filter(ErrorEvent.source == "error_log.purge").one()
        assert row.capture_kind == "explicit"

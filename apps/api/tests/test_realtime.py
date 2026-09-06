"""Avisos en vivo del portal.

Lo que se prueba acá no es que un evento viaje —eso es una cola—, sino las tres
formas en que este bus se rompería en silencio: publicar desde un hilo del
threadpool, quedarse sin lugar en la cola, y dejar suscriptores colgados.
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.services import realtime


@pytest.fixture(autouse=True)
def no_subscribers():
    """Ningún test empieza ni termina con suscriptores de otro."""
    realtime._subscribers.clear()
    yield
    assert realtime.subscriber_count() == 0, "un test dejó un suscriptor colgado"


def _subscriber(client_id, department_id):
    # Se construye dentro de un loop porque Subscriber captura el suyo al nacer.
    async def build():
        return realtime.Subscriber(client_id=client_id, department_id=department_id)

    return asyncio.run(build())


class TestReaches:
    """`reaches` tiene que espejar a `_visible`, o la frontera se parte en dos."""

    def test_a_department_only_gets_its_own(self):
        client_id, mine, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        subscriber = _subscriber(client_id, mine)
        assert realtime.reaches(subscriber, client_id, mine)
        assert not realtime.reaches(subscriber, client_id, other)

    def test_without_a_department_it_sees_the_whole_client(self):
        client_id = uuid.uuid4()
        subscriber = _subscriber(client_id, None)
        assert realtime.reaches(subscriber, client_id, uuid.uuid4())
        assert realtime.reaches(subscriber, client_id, None)

    def test_a_conversation_without_a_department_reaches_everyone(self):
        client_id = uuid.uuid4()
        assert realtime.reaches(_subscriber(client_id, uuid.uuid4()), client_id, None)

    def test_another_client_never_reaches(self):
        """La frontera entre inquilinos gana sobre cualquier otra regla."""
        subscriber = _subscriber(uuid.uuid4(), None)
        assert not realtime.reaches(subscriber, uuid.uuid4(), None)


def test_publish_from_a_worker_thread_reaches_the_stream():
    """El caso que se rompe sin ruido.

    `portal_mode` y `portal_status` son `def` sincrónicos, así que FastAPI los
    corre en un hilo del threadpool. Un publicador que asuma el event loop
    descartaría esos avisos sin lanzar nada: la pantalla se quedaría vieja y no
    habría error en ningún log.
    """
    client_id, conversation_id = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        stream = realtime.stream(client_id, None)
        assert await anext(stream) == ": ok\n\n"
        await asyncio.to_thread(
            realtime.publish, client_id=client_id, department_id=None, conversation_id=conversation_id
        )
        event = await asyncio.wait_for(anext(stream), timeout=2)
        await stream.aclose()
        return event

    event = asyncio.run(scenario())
    assert event == f"event: conversation\ndata: {conversation_id}\n\n"


def test_a_full_queue_drops_instead_of_raising():
    """Quien atiende va lento: se pierde un aviso, nunca el pedido que lo generó."""
    client_id = uuid.uuid4()

    async def scenario():
        stream = realtime.stream(client_id, None)
        await anext(stream)  # se suscribe, y después no consume nada más
        for _ in range(realtime.QUEUE_SIZE + 5):
            realtime.publish(client_id=client_id, department_id=None, conversation_id=uuid.uuid4())
        await asyncio.sleep(0.05)  # deja correr los call_soon_threadsafe
        queued = next(iter(realtime._subscribers)).queue.qsize()
        await stream.aclose()
        return queued

    assert asyncio.run(scenario()) == realtime.QUEUE_SIZE


def test_closing_the_stream_removes_the_subscriber():
    """Sin esto, cada pestaña que se cierra deja una cola que se llena para siempre."""
    client_id = uuid.uuid4()

    async def scenario():
        stream = realtime.stream(client_id, None)
        await anext(stream)
        during = realtime.subscriber_count()
        await stream.aclose()
        return during, realtime.subscriber_count()

    during, after = asyncio.run(scenario())
    assert (during, after) == (1, 0)


def test_a_quiet_stream_sends_a_heartbeat(monkeypatch):
    """Sin el latido, un proxy da la conexión por muerta y la corta."""
    monkeypatch.setattr(realtime, "HEARTBEAT_SECONDS", 0.01)

    async def scenario():
        stream = realtime.stream(uuid.uuid4(), None)
        await anext(stream)
        beat = await asyncio.wait_for(anext(stream), timeout=2)
        await stream.aclose()
        return beat

    assert asyncio.run(scenario()) == ": keep-alive\n\n"


def test_an_unknown_portal_never_opens_a_stream(client: TestClient):
    """Las dependencias corren antes de que empiece a salir el stream.

    Un endpoint que devuelve `StreamingResponse` sigue pasando por
    `_portal_client`: si no fuera así, un slug cualquiera abriría una conexión
    viva contra el bus antes de que nadie revise quién es.
    """
    response = client.get("/api/portal/no-existe/events")
    assert response.status_code == 404
    assert realtime.subscriber_count() == 0

"""Avisos en vivo para el portal, por Server-Sent Events.

Se manda una SEÑAL, no contenido: "algo cambió en esta conversación". Quien
escucha vuelve a pedir por los endpoints de siempre, que ya aplican
``_visible(user)``. Empujar la conversación por acá obligaría a re-derivar la
frontera de dependencias en cada lugar que publica un evento, y esa frontera
tiene que vivir en un solo lado o deja de ser una frontera.

El bus es en memoria, así que sirve para una instancia: un evento publicado en
un proceso no llega a quien esté conectado a otro. Es la misma limitación que
ya tienen ``ratelimit.py`` y ``_pending_replies`` en ``whatsapp_inbound.py``, y
se documenta igual que ellas en vez de fingir lo contrario. Con dos workers el
portal no se rompe: se queda viejo, y el refresco por intervalo que quedó de
respaldo lo tapa.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Cuántos avisos se le guardan a quien escucha antes de empezar a descartar.
# Un aviso perdido no pierde datos: el siguiente, o el refresco de respaldo,
# traen igual el estado completo.
QUEUE_SIZE = 32
# Un comentario cada tanto para que ningún proxy dé la conexión por muerta.
HEARTBEAT_SECONDS = 20


@dataclass
class Subscriber:
    client_id: uuid.UUID
    # None significa que ve todo el cliente, igual que en `_visible`.
    department_id: uuid.UUID | None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE))
    # El loop donde vive esta cola. Se guarda al suscribirse porque publish()
    # llega desde dos lados: los handlers `async def` corren en el loop, y los
    # `def` (portal_mode, portal_status) los corre FastAPI en un hilo del
    # threadpool. Sin esto, publicar desde un hilo descarta el evento en
    # silencio, que es la peor forma de romperse.
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)


_subscribers: set[Subscriber] = set()


def reaches(subscriber: Subscriber, client_id: uuid.UUID, department_id: uuid.UUID | None) -> bool:
    """Si este aviso le corresponde a quien escucha.

    Espeja a ``_visible``: quien no tiene dependencia ve todo lo de su cliente,
    y un evento sin dependencia le llega a todo el mundo de ese cliente.
    """
    if subscriber.client_id != client_id:
        return False
    if subscriber.department_id is None or department_id is None:
        return True
    return subscriber.department_id == department_id


def publish(*, client_id: uuid.UUID, department_id: uuid.UUID | None, conversation_id: uuid.UUID) -> None:
    """Avisa que una conversación cambió. Nunca lanza y nunca bloquea.

    Se puede llamar desde el event loop o desde un hilo del threadpool:
    ``call_soon_threadsafe`` es válido desde cualquiera de los dos, incluido el
    hilo del propio loop.
    """
    payload = str(conversation_id)
    for subscriber in list(_subscribers):
        if not reaches(subscriber, client_id, department_id):
            continue
        try:
            subscriber.loop.call_soon_threadsafe(_offer, subscriber, payload)
        except RuntimeError:
            # El loop de quien escuchaba ya cerró: su desuscripción viene en
            # camino. Un aviso perdido no justifica romper a quien publica.
            logger.debug("realtime: subscriber loop is closed, dropping the notice")


def _offer(subscriber: Subscriber, payload: str) -> None:
    try:
        subscriber.queue.put_nowait(payload)
    except asyncio.QueueFull:
        # Quien escucha va atrasado. Descartar es correcto: cada aviso dice lo
        # mismo —"volvé a pedir"— así que el que ya está encolado alcanza.
        pass


async def stream(client_id: uuid.UUID, department_id: uuid.UUID | None):
    """Generador de un stream SSE mientras quien escucha siga conectado."""
    subscriber = Subscriber(client_id=client_id, department_id=department_id)
    _subscribers.add(subscriber)
    try:
        # Un primer byte inmediato: hasta que algo salga, ni el navegador ni un
        # proxy en el medio saben que la conexión quedó abierta de verdad.
        yield ": ok\n\n"
        while True:
            try:
                conversation_id = await asyncio.wait_for(subscriber.queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"event: conversation\ndata: {conversation_id}\n\n"
    finally:
        _subscribers.discard(subscriber)


def subscriber_count() -> int:
    """Cuántas conexiones vivas hay. Existe para poder afirmarlo en un test."""
    return len(_subscribers)

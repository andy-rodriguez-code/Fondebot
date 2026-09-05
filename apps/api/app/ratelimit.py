"""Límite de tasa liviano por IP para endpoints públicos y sin autenticar.

Usa una ventana fija en memoria, que alcanza para un deployment de una sola
instancia. Un armado escalado horizontalmente necesitaría almacenamiento
compartido (por ejemplo Redis), o aplicar el límite en el reverse proxy que
está delante del gateway.
"""

import logging
import time
from functools import lru_cache
from ipaddress import ip_address, ip_network
from threading import Lock

from fastapi import HTTPException, Request, status

from .config import get_settings

logger = logging.getLogger("openlivery.ratelimit")


@lru_cache(maxsize=8)
def _trusted_networks(raw: str) -> tuple:
    networks = []
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        try:
            networks.append(ip_network(entry, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXIES ignora la entrada inválida %r", entry)
    return tuple(networks)


def _is_trusted_proxy(peer: str) -> bool:
    try:
        address = ip_address(peer)
    except ValueError:
        return False
    return any(address in network for network in _trusted_networks(get_settings().trusted_proxies))


def client_ip(request: Request) -> str:
    """Dirección del cliente, con la mejor precisión posible.

    ``X-Forwarded-For`` lo puede escribir quien llama, así que solo se lee
    cuando la conexión llega desde un proxy de confianza (``TRUSTED_PROXIES``).
    De esa cadena se toma la entrada **más a la derecha**: es la que agregó ese
    proxy, o sea el peer que él vio, y es la única que quien llama no controla.
    Un atacante puede anteponer las entradas que quiera y ninguna cuenta.

    Esto asume un solo salto de proxy de confianza, que es la topología del
    stack (gateway Caddy delante de la API). Con varios proxies encadenados
    habría que descartar tantas entradas como saltos confiables haya.
    """
    peer = request.client.host if request.client else None
    if peer and _is_trusted_proxy(peer):
        entries = [entry.strip() for entry in request.headers.get("x-forwarded-for", "").split(",") if entry.strip()]
        if entries:
            return entries[-1]
    return peer or "unknown"


class RateLimiter:
    """Dependencia de FastAPI que permite ``times`` requests cada ``seconds`` por IP."""

    def __init__(self, times: int, seconds: int, *, name: str) -> None:
        self.times = times
        self.seconds = seconds
        self.name = name
        self._hits: dict[str, tuple[int, float]] = {}
        self._lock = Lock()

    def _register(self, identifier: str) -> tuple[int, float]:
        now = time.monotonic()
        with self._lock:
            count, window_start = self._hits.get(identifier, (0, now))
            if now - window_start >= self.seconds:
                count, window_start = 0, now
            count += 1
            self._hits[identifier] = (count, window_start)
            # Acotar la memoria: descartar las ventanas que ya vencieron.
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if now - v[1] < self.seconds}
        return count, window_start

    def __call__(self, request: Request) -> None:
        if not get_settings().rate_limit_enabled:
            return
        count, window_start = self._register(f"{self.name}:{client_ip(request)}")
        if count > self.times:
            retry_after = max(1, int(self.seconds - (time.monotonic() - window_start)))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down and try again.",
                headers={"Retry-After": str(retry_after)},
            )


# Limitadores compartidos. Los endpoints de credenciales son estrictos (defensa
# contra fuerza bruta); el endpoint de mensajes del widget se limita porque cada
# llamada gasta tokens del LLM.
login_rate_limit = RateLimiter(10, 60, name="login")
widget_rate_limit = RateLimiter(30, 60, name="widget")
public_asset_rate_limit = RateLimiter(60, 60, name="public-asset")
# El webhook de Meta se autentica con su firma HMAC; este límite generoso solo
# protege contra avalanchas de tráfico sin firmar.
whatsapp_cloud_webhook_rate_limit = RateLimiter(300, 60, name="whatsapp-cloud-webhook")
# Mismos números que login_rate_limit: aceptar una invitación es otro endpoint
# público sin autenticar, con la misma defensa contra fuerza bruta de tokens.
invitation_rate_limit = RateLimiter(10, 60, name="invitation")

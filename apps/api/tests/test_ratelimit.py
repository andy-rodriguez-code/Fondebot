from types import SimpleNamespace

from app import config
from app.main import app
from app.ratelimit import RateLimiter, client_ip, invitation_rate_limit, login_rate_limit


def _request(headers=None, host="1.2.3.4"):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


def test_client_ip_reads_forwarded_for_from_a_trusted_proxy():
    # 172.18.0.2 is the docker bridge network the gateway runs on.
    request = _request(headers={"x-forwarded-for": "9.9.9.9"}, host="172.18.0.2")
    assert client_ip(request) == "9.9.9.9"


def test_client_ip_ignores_forwarded_for_from_an_untrusted_peer():
    request = _request(headers={"x-forwarded-for": "9.9.9.9"}, host="1.2.3.4")
    assert client_ip(request) == "1.2.3.4"


def test_client_ip_ignores_entries_the_caller_prepended():
    # Only the rightmost entry was written by the trusted proxy; everything to
    # its left is whatever the caller decided to send.
    request = _request(headers={"x-forwarded-for": "9.9.9.9, 203.0.113.7"}, host="172.18.0.2")
    assert client_ip(request) == "203.0.113.7"


def test_client_ip_falls_back_to_peer():
    assert client_ip(_request()) == "1.2.3.4"


def test_register_counts_within_window_and_resets():
    limiter = RateLimiter(times=2, seconds=60, name="unit")
    assert limiter._register("a")[0] == 1
    assert limiter._register("a")[0] == 2
    assert limiter._register("a")[0] == 3
    # A different identifier is tracked independently.
    assert limiter._register("b")[0] == 1


def test_spoofed_forwarded_for_does_not_reset_the_login_bucket(client, monkeypatch):
    """A caller sending a fresh X-Forwarded-For per request used to get a fresh
    bucket every time, which removed the brute-force limit entirely."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    config.get_settings.cache_clear()
    login_rate_limit._hits.clear()
    try:
        creds = {"email": "nobody@example.com", "password": "wrong-password"}
        for attempt in range(10):
            spoofed = {"X-Forwarded-For": f"9.9.9.{attempt}"}
            assert client.post("/api/auth/login", json=creds, headers=spoofed).status_code == 401
        blocked = client.post("/api/auth/login", json=creds, headers={"X-Forwarded-For": "9.9.9.99"})
        assert blocked.status_code == 429
    finally:
        login_rate_limit._hits.clear()
        config.get_settings.cache_clear()


def test_login_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    config.get_settings.cache_clear()
    login_rate_limit._hits.clear()
    try:
        creds = {"email": "nobody@example.com", "password": "wrong-password"}
        for _ in range(10):
            assert client.post("/api/auth/login", json=creds).status_code == 401
        blocked = client.post("/api/auth/login", json=creds)
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
    finally:
        login_rate_limit._hits.clear()
        config.get_settings.cache_clear()


def test_invitation_accept_is_rate_limited(client, monkeypatch):
    """Mirrors the login case: the public accept endpoint is another
    unauthenticated surface an attacker could hammer with guessed tokens."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    config.get_settings.cache_clear()
    invitation_rate_limit._hits.clear()
    try:
        body = {"token": "un-token-que-nunca-existio-1234567890", "password": "una-contrasena-larga"}
        for _ in range(10):
            assert client.post("/api/portal/no-existe/invitations/accept", json=body).status_code == 400
        blocked = client.post("/api/portal/no-existe/invitations/accept", json=body)
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
    finally:
        invitation_rate_limit._hits.clear()
        config.get_settings.cache_clear()


def test_every_public_widget_route_is_rate_limited():
    """Ninguna ruta del widget puede quedar sin límite.

    Se afirma sobre la app entera y no sobre una ruta concreta a propósito. El
    hallazgo que originó esto fue que ``GET /api/widget/{public_id}`` era la
    única sin límite entre seis hermanas: nadie lo sacó, simplemente nunca se
    lo pusieron. Un test por ruta no habría dicho nada de la séptima.

    Todo lo que cuelga de ``/api/widget/`` es público y sin autenticar: es la
    superficie que cualquiera alcanza desde el sitio de la clientela.
    """
    unlimited = [
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/widget/")
        and not any(isinstance(dep.dependency, RateLimiter) for dep in getattr(route, "dependencies", []))
    ]
    assert unlimited == []

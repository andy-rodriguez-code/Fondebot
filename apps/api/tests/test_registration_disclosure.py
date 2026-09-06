"""Qué revela el registro sobre qué direcciones ya tienen cuenta.

El hallazgo S-9 de la auditoría apunta al 409 "A user with that email already
exists". Lo que no dice es que en la postura por defecto esa rama no se alcanza:
el registro se cierra apenas existe una agencia, y ese chequeo corre ANTES de
mirar el correo. Los tests de acá fijan esa propiedad, que es la que hace que el
hallazgo no aplique, y dejan escrito qué cambia cuando alguien enciende
``ALLOW_MULTI_AGENCY``.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

PASSWORD = "very-secure-key"
EXISTING = "laura@norte.com"


def _register(client: TestClient, email: str, agency: str = "South Studio"):
    return client.post(
        "/api/auth/register",
        json={"agency_name": agency, "name": "Mario", "email": email, "password": PASSWORD},
    )


@pytest.fixture
def with_one_agency(client: TestClient) -> TestClient:
    assert _register(client, EXISTING, agency="North Studio").status_code == 201
    client.post("/api/auth/logout")
    return client


def test_registration_says_the_same_thing_about_any_address(with_one_agency: TestClient):
    """La propiedad que hace que S-9 no aplique por defecto.

    Una dirección que ya tiene cuenta y una que no reciben la MISMA respuesta,
    porque el registro cerrado se responde antes de consultar el correo. Sin
    esto, quien prueba direcciones distingue una de otra.
    """
    taken = _register(with_one_agency, EXISTING)
    free = _register(with_one_agency, "nadie@norte.com")

    assert (taken.status_code, taken.json()) == (free.status_code, free.json())
    assert taken.status_code == 403


def test_login_does_not_distinguish_either(with_one_agency: TestClient):
    """La otra puerta por la que se probaría lo mismo."""
    known = with_one_agency.post("/api/auth/login", json={"email": EXISTING, "password": "wrong-password"})
    unknown = with_one_agency.post("/api/auth/login", json={"email": "nadie@norte.com", "password": "wrong-password"})

    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert known.status_code == 401


def test_multi_agency_mode_does_distinguish(with_one_agency: TestClient, monkeypatch):
    """El único caso donde S-9 se alcanza, fijado a propósito.

    Con ``ALLOW_MULTI_AGENCY`` el registro queda abierto a internet y el 409
    dice si una dirección ya tiene cuenta. Este test no aprueba ese
    comportamiento: lo deja escrito, para que el día que alguien lo cambie sea
    una decisión y no un accidente. Cerrarlo de verdad pide verificar la
    dirección por correo antes de crear nada, que es otro cambio.

    El costo de probar direcciones no es cero igual: ``/register`` comparte el
    limitador de ``login``, 10 intentos por minuto y por IP.
    """
    monkeypatch.setattr(get_settings(), "allow_multi_agency", True)

    taken = _register(with_one_agency, EXISTING)
    free = _register(with_one_agency, "otra@norte.com")

    assert taken.status_code == 409
    assert free.status_code == 201

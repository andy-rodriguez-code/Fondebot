"""El límite de 72 bytes de bcrypt, en las rutas donde antes salía como 500.

`bcrypt` 4 dejó de truncar en silencio y ahora lanza `ValueError` con cualquier
entrada más larga. `schemas.py` aceptaba hasta 128 *caracteres*, así que la
contraseña larga llegaba entera a `bcrypt` y el error subía sin manejar.

El caso feo era el login: es público, sin autenticar, y cualquiera podía sacarle
un error del servidor mandando una contraseña larga.
"""

from fastapi.testclient import TestClient

from app.security import BCRYPT_MAX_BYTES, hash_password, verify_password

# 72 caracteres ASCII = 72 bytes: el máximo que bcrypt acepta, y tiene que andar.
AT_THE_LIMIT = "a" * BCRYPT_MAX_BYTES
# 73 bytes: uno de más.
OVER_BY_ONE = "a" * (BCRYPT_MAX_BYTES + 1)
# 24 emojis = 24 caracteres pero 96 bytes. Es el caso que un `max_length` de
# Pydantic deja pasar, porque cuenta caracteres y bcrypt cuenta bytes.
SHORT_BUT_TOO_MANY_BYTES = "🔐" * 24


def _registration(password: str) -> dict:
    return {
        "agency_name": "North Studio",
        "name": "Laura Mendez",
        "email": "laura@norte.com",
        "password": password,
    }


class TestVerifyPassword:
    def test_an_over_long_password_is_wrong_not_an_error(self):
        """Ningún hash guardado pudo salir de una entrada más larga que el
        límite, así que esto no coincide con nada. False es la respuesta, no una
        excepción."""
        assert verify_password(OVER_BY_ONE, hash_password(AT_THE_LIMIT)) is False

    def test_the_limit_itself_still_round_trips(self):
        assert verify_password(AT_THE_LIMIT, hash_password(AT_THE_LIMIT)) is True

    def test_multibyte_under_the_limit_round_trips(self):
        """Una tilde gasta dos bytes, pero mientras entre, tiene que funcionar."""
        password = "contraseña-muy-difícil-ñ"
        assert len(password.encode()) <= BCRYPT_MAX_BYTES
        assert verify_password(password, hash_password(password)) is True


class TestRegister:
    def test_an_over_long_password_is_rejected(self, client: TestClient):
        assert client.post("/api/auth/register", json=_registration(OVER_BY_ONE)).status_code == 422

    def test_few_characters_can_still_be_too_many_bytes(self, client: TestClient):
        """24 caracteres, 96 bytes. Un límite por caracteres lo dejaría pasar."""
        assert len(SHORT_BUT_TOO_MANY_BYTES) < 72
        response = client.post("/api/auth/register", json=_registration(SHORT_BUT_TOO_MANY_BYTES))
        assert response.status_code == 422

    def test_the_limit_itself_is_accepted(self, client: TestClient):
        assert client.post("/api/auth/register", json=_registration(AT_THE_LIMIT)).status_code == 201


class TestLogin:
    """La ruta pública, que es la que de verdad importa."""

    def test_an_over_long_password_is_a_refusal_not_a_server_error(self, client: TestClient):
        client.post("/api/auth/register", json=_registration(AT_THE_LIMIT))
        response = client.post("/api/auth/login", json={"email": "laura@norte.com", "password": OVER_BY_ONE})
        # 401, nunca 500: sin esto cualquiera sin cuenta saca un error del
        # servidor mandando una contraseña larga.
        assert response.status_code == 401

    def test_the_right_password_still_signs_in(self, client: TestClient):
        client.post("/api/auth/register", json=_registration(AT_THE_LIMIT))
        client.post("/api/auth/logout")
        response = client.post("/api/auth/login", json={"email": "laura@norte.com", "password": AT_THE_LIMIT})
        assert response.status_code == 200


def test_portal_user_creation_rejects_an_over_long_password(authenticated_client: TestClient):
    """El alta de una persona del portal hashea igual que el registro."""
    customer = authenticated_client.post(
        "/api/clients",
        json={"name": "Fondo Norte", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    response = authenticated_client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "tesoreria@fondo.com", "password": OVER_BY_ONE, "name": "Ana"},
    )
    assert response.status_code == 422

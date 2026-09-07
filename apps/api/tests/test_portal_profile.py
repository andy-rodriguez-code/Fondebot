"""El perfil de quien atiende, y la cara detrás de cada respuesta.

Un hilo mostraba un nombre y nada más, así que una respuesta de una persona y
una del agente se veían iguales. Lo que se prueba acá es que el mensaje diga
QUIÉN lo escribió, que cada quien pueda cambiar sus propios datos, y —lo que
más importa— que no pueda cambiar los que no le corresponden.
"""

import io

from fastapi.testclient import TestClient

PASSWORD = "una-clave-de-prueba-larga"
# Un PNG de 1x1, el archivo valido mas chico que se puede subir.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001" "0d0a2db4" "0000000049454e44ae426082"
)


def _client_with_portal(admin: TestClient) -> dict:
    customer = admin.post(
        "/api/clients",
        json={"name": "Cooperativa", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    admin.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "tesa@cooperativa.com", "password": PASSWORD, "name": "Tesa"},
    )
    return admin.patch(f"/api/clients/{customer['id']}/portal", json={"portal_enabled": True}).json()


def _signed_in(app, slug: str, email: str = "tesa@cooperativa.com", password: str = PASSWORD) -> TestClient:
    portal = TestClient(app)
    response = portal.post(f"/api/portal/{slug}/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return portal


class TestChangingYourOwnDetails:
    def test_name_and_address(self, authenticated_client: TestClient):
        customer = _client_with_portal(authenticated_client)
        portal = _signed_in(authenticated_client.app, customer["portal_slug"])

        updated = portal.patch(
            f"/api/portal/{customer['portal_slug']}/me", json={"name": "Tesa Ruiz", "email": "TESA.RUIZ@cooperativa.com"}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["user_name"] == "Tesa Ruiz"
        # La direccion se guarda en minusculas, igual que en el alta.
        assert updated.json()["user_email"] == "tesa.ruiz@cooperativa.com"

    def test_the_new_password_is_the_one_that_signs_in(self, authenticated_client: TestClient):
        customer = _client_with_portal(authenticated_client)
        slug = customer["portal_slug"]
        portal = _signed_in(authenticated_client.app, slug)

        assert portal.patch(f"/api/portal/{slug}/me", json={"password": "otra-clave-bien-larga"}).status_code == 200

        fresh = TestClient(authenticated_client.app)
        assert fresh.post(f"/api/portal/{slug}/login", json={"email": "tesa@cooperativa.com", "password": PASSWORD}).status_code == 401
        assert fresh.post(
            f"/api/portal/{slug}/login", json={"email": "tesa@cooperativa.com", "password": "otra-clave-bien-larga"}
        ).status_code == 200

    def test_a_long_password_is_refused_here_too(self, authenticated_client: TestClient):
        """El limite de bcrypt vale en todas las puertas, no solo en el alta."""
        customer = _client_with_portal(authenticated_client)
        portal = _signed_in(authenticated_client.app, customer["portal_slug"])
        response = portal.patch(f"/api/portal/{customer['portal_slug']}/me", json={"password": "a" * 200})
        assert response.status_code == 422

    def test_taking_a_colleagues_address_is_refused(self, authenticated_client: TestClient):
        customer = _client_with_portal(authenticated_client)
        authenticated_client.post(
            f"/api/clients/{customer['id']}/portal-users",
            json={"email": "otra@cooperativa.com", "password": PASSWORD, "name": "Otra"},
        )
        portal = _signed_in(authenticated_client.app, customer["portal_slug"])
        response = portal.patch(f"/api/portal/{customer['portal_slug']}/me", json={"email": "otra@cooperativa.com"})
        assert response.status_code == 409


def test_the_department_is_not_something_you_can_change_about_yourself(authenticated_client: TestClient):
    """La decision que NO es de quien atiende.

    Cambiarse la dependencia seria elegir que conversaciones ve. El campo no
    existe en el schema, asi que mandarlo no hace nada — y este test es lo que
    hace que agregarlo despues sea una decision y no un descuido.
    """
    customer = _client_with_portal(authenticated_client)
    slug = customer["portal_slug"]
    other = authenticated_client.post(
        f"/api/clients/{customer['id']}/departments", json={"name": "Contabilidad", "agent_id": None}
    )
    portal = _signed_in(authenticated_client.app, slug)

    updated = portal.patch(f"/api/portal/{slug}/me", json={"department_id": (other.json() or {}).get("id")})
    assert updated.status_code == 200
    assert updated.json()["department_name"] is None


class TestThePhoto:
    def test_upload_serve_and_remove(self, authenticated_client: TestClient):
        customer = _client_with_portal(authenticated_client)
        slug = customer["portal_slug"]
        portal = _signed_in(authenticated_client.app, slug)

        uploaded = portal.put(
            f"/api/portal/{slug}/me/avatar", files={"file": ("cara.png", io.BytesIO(PNG), "image/png")}
        )
        assert uploaded.status_code == 200, uploaded.text
        url = uploaded.json()["avatar_url"]
        assert url and url.endswith("/avatar")

        served = portal.get(url)
        assert served.status_code == 200
        assert served.headers["content-type"].startswith("image/png")

        assert portal.delete(f"/api/portal/{slug}/me/avatar").status_code == 204
        assert portal.get(f"/api/portal/{slug}/me").json()["avatar_url"] is None

    def test_an_svg_is_refused(self, authenticated_client: TestClient):
        """Una cara no necesita ser un documento ejecutable.

        Un SVG puede traer scripts. Se sirve con nosniff y CSP, pero la forma
        barata de no tener ese problema es no aceptarlo.
        """
        customer = _client_with_portal(authenticated_client)
        slug = customer["portal_slug"]
        portal = _signed_in(authenticated_client.app, slug)
        response = portal.put(
            f"/api/portal/{slug}/me/avatar",
            files={"file": ("cara.svg", io.BytesIO(b"<svg xmlns='http://www.w3.org/2000/svg'/>"), "image/svg+xml")},
        )
        assert response.status_code == 415

    def test_a_photo_needs_a_session(self, authenticated_client: TestClient, client: TestClient):
        customer = _client_with_portal(authenticated_client)
        slug = customer["portal_slug"]
        portal = _signed_in(authenticated_client.app, slug)
        url = portal.put(
            f"/api/portal/{slug}/me/avatar", files={"file": ("cara.png", io.BytesIO(PNG), "image/png")}
        ).json()["avatar_url"]

        assert client.get(url).status_code == 401

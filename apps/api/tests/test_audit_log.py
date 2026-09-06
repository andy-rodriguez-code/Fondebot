"""El registro de auditoría.

Existe para la pregunta que se hace después de un incidente: quién cambió esa
credencial, quién dio de alta a esa persona, quién editó esas instrucciones.
Lo que se prueba acá es que la respuesta esté, que sea legible sin depender de
otras tablas, y que registrar el cambio de un secreto no guarde el secreto.
"""

import uuid

from fastapi.testclient import TestClient

KEY = "sk-esto-es-una-credencial-de-prueba"


def _entries(client: TestClient) -> list[dict]:
    response = client.get("/api/audit")
    assert response.status_code == 200, response.text
    return response.json()


def _customer(client: TestClient) -> dict:
    return client.post(
        "/api/clients",
        json={"name": "Cooperativa", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()


def test_nothing_happened_yet(authenticated_client: TestClient):
    assert _entries(authenticated_client) == []


class TestProviderCredentials:
    def test_setting_a_key_is_recorded(self, authenticated_client: TestClient):
        assert authenticated_client.put("/api/providers/openai", json={"api_key": KEY}).status_code == 200

        entry = _entries(authenticated_client)[0]
        assert entry["action"] == "provider.credentials_changed"
        assert entry["target_label"] == "openai"
        assert entry["actor_type"] == "user"
        assert entry["actor_label"] == "ana@prisma.com"

    def test_the_key_itself_is_never_recorded(self, authenticated_client: TestClient):
        """La razón por la que no hay columna con el detalle del cambio.

        En un cambio de credencial, "lo que cambió" ES la credencial. Se
        registra que pasó y sobre qué, nunca el valor.
        """
        authenticated_client.put("/api/providers/openai", json={"api_key": KEY})

        raw = authenticated_client.get("/api/audit").text
        assert KEY not in raw
        assert "sk-" not in raw

    def test_removing_a_key_is_recorded_too(self, authenticated_client: TestClient):
        authenticated_client.put("/api/providers/openai", json={"api_key": KEY})
        assert authenticated_client.delete("/api/providers/openai").status_code == 204

        actions = [entry["action"] for entry in _entries(authenticated_client)]
        assert actions[0] == "provider.credentials_removed"
        assert actions[1] == "provider.credentials_changed"


class TestPortalUsers:
    def test_creating_one_is_recorded_with_the_address(self, authenticated_client: TestClient):
        customer = _customer(authenticated_client)
        created = authenticated_client.post(
            f"/api/clients/{customer['id']}/portal-users",
            json={"email": "tesa@cooperativa.com", "password": "una-clave-larga-y-buena", "name": "Tesa"},
        )
        assert created.status_code == 201, created.text

        entry = _entries(authenticated_client)[0]
        assert entry["action"] == "portal_user.created"
        assert entry["target_label"] == "tesa@cooperativa.com"
        assert entry["target_id"] == created.json()["id"]

    def test_deactivating_one_is_recorded(self, authenticated_client: TestClient):
        customer = _customer(authenticated_client)
        created = authenticated_client.post(
            f"/api/clients/{customer['id']}/portal-users",
            json={"email": "tesa@cooperativa.com", "password": "una-clave-larga-y-buena", "name": "Tesa"},
        ).json()

        updated = authenticated_client.patch(
            f"/api/clients/{customer['id']}/portal-users/{created['id']}", json={"is_active": False}
        )
        assert updated.status_code == 200, updated.text
        assert _entries(authenticated_client)[0]["action"] == "portal_user.updated"


class TestAgentInstructions:
    def _agent(self, client: TestClient) -> dict:
        customer = _customer(client)
        return client.post("/api/agents", json={"client_id": customer["id"], "name": "Asistente"}).json()

    def test_changing_them_is_recorded(self, authenticated_client: TestClient):
        agent = self._agent(authenticated_client)
        response = authenticated_client.patch(
            f"/api/agents/{agent['id']}", json={"instructions": "Responde siempre en dos frases."}
        )
        assert response.status_code == 200, response.text

        entry = _entries(authenticated_client)[0]
        assert entry["action"] == "agent.instructions_changed"
        assert entry["target_label"] == "Asistente"

    def test_an_unrelated_edit_is_not(self, authenticated_client: TestClient):
        """El registro tiene que seguir siendo legible.

        Anotar cada PATCH, incluidos los que no tocan las instrucciones, lo
        llenaría de ruido y volvería inútil el único lugar donde se busca algo
        concreto.
        """
        agent = self._agent(authenticated_client)
        authenticated_client.patch(f"/api/agents/{agent['id']}", json={"name": "Otro nombre"})
        assert _entries(authenticated_client) == []

    def test_rewriting_the_same_text_is_not(self, authenticated_client: TestClient):
        agent = self._agent(authenticated_client)
        authenticated_client.patch(f"/api/agents/{agent['id']}", json={"instructions": "Se breve."})
        authenticated_client.patch(f"/api/agents/{agent['id']}", json={"instructions": "Se breve."})
        assert len(_entries(authenticated_client)) == 1


def test_reading_it_needs_a_session(client: TestClient):
    assert client.get("/api/audit").status_code == 401


def test_there_is_no_way_to_edit_or_delete_an_entry(authenticated_client: TestClient):
    """Append-only no es una convención, es que no existe el endpoint.

    Un registro que quien administra puede corregir no responde la pregunta
    para la que existe.
    """
    authenticated_client.put("/api/providers/openai", json={"api_key": KEY})
    entry_id = _entries(authenticated_client)[0]["id"]

    for method in (authenticated_client.delete, authenticated_client.patch, authenticated_client.put):
        assert method(f"/api/audit/{entry_id}").status_code in (404, 405)
    assert len(_entries(authenticated_client)) == 1


def test_the_entry_survives_the_actor(authenticated_client: TestClient):
    """Por qué el nombre se copia en vez de resolverse con un join.

    Una fila de auditoría que se vuelve ilegible cuando desaparece la cuenta
    que la generó no sirve, y ese es justo el caso en que se la va a leer.
    """
    customer = _customer(authenticated_client)
    created = authenticated_client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "tesa@cooperativa.com", "password": "una-clave-larga-y-buena", "name": "Tesa"},
    ).json()
    assert authenticated_client.delete(f"/api/clients/{customer['id']}/portal-users/{created['id']}").status_code in (
        204,
        200,
    )

    entry = _entries(authenticated_client)[0]
    assert entry["target_label"] == "tesa@cooperativa.com"
    assert uuid.UUID(entry["target_id"])

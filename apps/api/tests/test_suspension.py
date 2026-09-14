"""Suspender una empresa le corta el servicio, sin tocarle un dato.

`Client.is_active` existía desde el principio y no cortaba nada: el único
lugar que lo leía era el contador del panel. Una empresa que dejaba de pagar
seguía atendiendo por WhatsApp toda la noche.

Lo que se prueba acá es que el corte alcance los cuatro caminos por los que
entra una petición de afuera —portal, widget, WhatsApp y mobile—, que no se
borre nada, y que el corte sea para la empresa y no para quien la administra.
"""

import json
import uuid

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal
from app.models import Conversation
from test_whatsapp_cloud import APP_SECRET, _setup_channel, _sign, _webhook_payload

PASSWORD = "una-clave-de-prueba-larga"


def _empresa_con_portal(admin: TestClient) -> dict:
    """Una empresa activa, con portal abierto y una persona que lo usa."""
    customer = admin.post(
        "/api/clients",
        json={"name": "Panaderia Lopez", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    admin.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "ada@panaderia.com", "password": PASSWORD, "name": "Ada"},
    )
    return admin.patch(f"/api/clients/{customer['id']}/portal", json={"portal_enabled": True}).json()


def _suspender(admin: TestClient, client_id: str) -> None:
    response = admin.patch(f"/api/clients/{client_id}", json={"is_active": False})
    assert response.status_code == 200, response.text


def _reactivar(admin: TestClient, client_id: str) -> None:
    response = admin.patch(f"/api/clients/{client_id}", json={"is_active": True})
    assert response.status_code == 200, response.text


class TestElPortalSeCierra:
    """Suspendida, su gente no entra: ni con credenciales correctas, ni con la
    sesión que ya tenía abierta."""

    def test_el_login_se_rechaza(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        portal = TestClient(authenticated_client.app)
        response = portal.post(
            f"/api/portal/{customer['portal_slug']}/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )

        assert response.status_code == 403
        assert "suspend" in response.json()["detail"].lower()

    def test_una_sesion_ya_abierta_deja_de_servir(self, authenticated_client: TestClient):
        # La sesión se abre ANTES de suspender: es el caso real, alguien
        # trabajando cuando se corta el servicio.
        customer = _empresa_con_portal(authenticated_client)
        portal = TestClient(authenticated_client.app)
        assert portal.post(
            f"/api/portal/{customer['portal_slug']}/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        ).status_code == 200

        _suspender(authenticated_client, customer["id"])

        response = portal.get(f"/api/portal/{customer['portal_slug']}/conversations")
        assert response.status_code == 403

    def test_reactivar_devuelve_el_acceso(self, authenticated_client: TestClient):
        # Suspender no borra: es lo que separa "te cortamos" de "te perdimos".
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])
        _reactivar(authenticated_client, customer["id"])

        portal = TestClient(authenticated_client.app)
        response = portal.post(
            f"/api/portal/{customer['portal_slug']}/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )

        assert response.status_code == 200


class TestElWidgetDejaDeAtender:
    """El chat embebido en el sitio de la empresa deja de cargar. Un widget que
    responde es un servicio que se está prestando."""

    def test_la_configuracion_del_widget_no_se_entrega(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        agent = authenticated_client.post(
            "/api/agents",
            json={
                "client_id": customer["id"],
                "name": "Bot Panaderia",
                "instructions": "Atende pedidos.",
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        ).json()
        authenticated_client.patch(f"/api/agents/{agent['id']}", json={"widget_enabled": True})
        public_id = authenticated_client.get(f"/api/agents/{agent['id']}").json()["widget_public_id"]

        visitante = TestClient(authenticated_client.app)
        assert visitante.get(f"/api/widget/{public_id}").status_code == 200

        _suspender(authenticated_client, customer["id"])

        assert visitante.get(f"/api/widget/{public_id}").status_code == 404


class TestWhatsappDejaDeContestar:
    """El canal que de verdad cuesta plata cuando no se corta."""

    def test_el_mensaje_entrante_se_rechaza(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        agent = authenticated_client.post(
            "/api/agents",
            json={
                "client_id": customer["id"],
                "name": "Bot Panaderia",
                "instructions": "Atende pedidos.",
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        ).json()
        channel = authenticated_client.put(
            f"/api/whatsapp/channels/{customer['id']}",
            json={"agent_id": agent["id"]},
        ).json()

        _suspender(authenticated_client, customer["id"])

        puente = TestClient(authenticated_client.app)
        response = puente.post(
            f"/api/internal/whatsapp/channels/{channel['id']}/inbound",
            json={
                "external_message_id": "m1",
                "remote_jid": "5491100000000@s.whatsapp.net",
                "sender_name": "Cliente",
                "text": "hola",
            },
            headers={"X-Bridge-Token": get_settings().whatsapp_bridge_token},
        )

        assert response.status_code == 409
        assert "suspend" in response.json()["detail"].lower()


class TestElWebhookDeMetaDescarta:
    """El canal de las empresas grandes. Se responde 200 y se descarta, y NO se
    rechaza: Meta reintenta todo lo que no sea 2xx, así que un 403 convertiría a
    una empresa suspendida en tráfico infinito contra el servidor."""

    def test_responde_200_y_no_procesa(self, authenticated_client: TestClient):
        customer, agent, channel = _setup_channel(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        payload = _webhook_payload(
            [{"from": "5730011", "id": "wamid.suspendida", "type": "text", "text": {"body": "hola"}}]
        )
        raw = json.dumps(payload).encode()

        meta = TestClient(authenticated_client.app)
        response = meta.post(
            f"/api/public/whatsapp-cloud/channels/{channel['id']}/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(raw, APP_SECRET)},
        )

        assert response.status_code == 200

        # Y lo que de verdad importa: no se creó ninguna conversación.
        conversaciones = authenticated_client.get("/api/conversations/inbox").json()
        assert conversaciones == []

    def test_una_firma_invalida_sigue_dando_403(self, authenticated_client: TestClient):
        # El control de suspensión va DESPUÉS de la firma. Si se adelantara, le
        # daría a cualquiera una forma de averiguar qué canales existen y cuáles
        # están suspendidos, sin credencial alguna.
        customer, agent, channel = _setup_channel(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        payload = _webhook_payload(
            [{"from": "5730011", "id": "wamid.falsa", "type": "text", "text": {"body": "hola"}}]
        )
        raw = json.dumps(payload).encode()

        meta = TestClient(authenticated_client.app)
        response = meta.post(
            f"/api/public/whatsapp-cloud/channels/{channel['id']}/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(raw, "secreto-equivocado")},
        )

        assert response.status_code == 403


class TestLaAppMobileSeCierra:
    """La cuarta puerta. Tiene su propio login y NO pasa por la dependencia del
    portal, así que cerrar el portal web no la cierra."""

    def test_el_login_mobile_se_rechaza(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        telefono = TestClient(authenticated_client.app)
        response = telefono.post(
            "/api/mobile/sign-in",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )

        assert response.status_code == 401

    def test_una_sesion_mobile_ya_abierta_deja_de_servir(self, authenticated_client: TestClient):
        # El caso real: alguien con la app abierta cuando se corta el servicio.
        # La sesión se abre ANTES de suspender, y el token se reusa contra una
        # ruta autenticada: eso es lo que prueba que la sesión, y no solo el
        # login, deje de servir.
        customer = _empresa_con_portal(authenticated_client)
        telefono = TestClient(authenticated_client.app)
        session = telefono.post(
            "/api/mobile/sign-in",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )
        assert session.status_code == 200
        token = session.json()["token"]

        _suspender(authenticated_client, customer["id"])

        response = telefono.get(
            "/api/mobile/session",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401


def _seed_conversation(*, agency_id, client_id: str, agent_id: str) -> uuid.UUID:
    """Inserta una conversación directo, como test_dashboard.py: lo que se
    prueba acá es que siga visible después de suspender, no cómo nace."""
    with SessionLocal() as db:
        conversation = Conversation(
            agency_id=agency_id,
            client_id=uuid.UUID(client_id),
            agent_id=uuid.UUID(agent_id),
            title="Caso de la panadería",
            channel="whatsapp_cloud",
        )
        db.add(conversation)
        db.commit()
        return conversation.id


class TestElDuenoNoPierdeAcceso:
    """El corte es para la empresa, no para quien la administra.

    Si suspender también te dejara a vos afuera, no podrías revisar su cuenta
    justo cuando hay que hablar de la deuda. Y los datos tienen que seguir ahí:
    suspender no es borrar.
    """

    def test_la_empresa_suspendida_sigue_en_el_listado(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        listado = authenticated_client.get("/api/clients").json()

        assert any(row["id"] == customer["id"] for row in listado)

    def test_su_ficha_se_sigue_abriendo(self, authenticated_client: TestClient):
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        response = authenticated_client.get(f"/api/clients/{customer['id']}")

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_su_gente_sigue_existiendo(self, authenticated_client: TestClient):
        # Suspender no borra cuentas. Reactivar tiene que devolver el equipo
        # completo, sin que nadie vuelva a cargar a mano quién trabajaba ahí.
        customer = _empresa_con_portal(authenticated_client)
        _suspender(authenticated_client, customer["id"])

        gente = authenticated_client.get(f"/api/clients/{customer['id']}/portal-users").json()

        assert [row["email"] for row in gente] == ["ada@panaderia.com"]

    def test_sus_conversaciones_se_siguen_viendo_en_la_bandeja(self, authenticated_client: TestClient):
        # Suspender no borra el historial: el dueño tiene que poder seguir
        # leyendo lo que esa empresa ya conversó, aunque el servicio esté
        # cortado.
        customer = _empresa_con_portal(authenticated_client)
        agent = authenticated_client.post(
            "/api/agents",
            json={
                "client_id": customer["id"],
                "name": "Bot Panaderia",
                "instructions": "Atende pedidos.",
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        ).json()
        agency_id = uuid.UUID(authenticated_client.get("/api/agency").json()["id"])
        conversation_id = _seed_conversation(agency_id=agency_id, client_id=customer["id"], agent_id=agent["id"])

        _suspender(authenticated_client, customer["id"])

        bandeja = authenticated_client.get("/api/conversations/inbox").json()
        assert any(row["id"] == str(conversation_id) for row in bandeja)

    def test_reactivar_devuelve_el_servicio_completo(self, authenticated_client: TestClient):
        # No alcanza con que el login vuelva a andar (ya lo cubre
        # TestElPortalSeCierra): reactivar tiene que devolver también el acceso
        # a lo que esa gente ya tenía, no solo la puerta de entrada.
        customer = _empresa_con_portal(authenticated_client)
        agent = authenticated_client.post(
            "/api/agents",
            json={
                "client_id": customer["id"],
                "name": "Bot Panaderia",
                "instructions": "Atende pedidos.",
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        ).json()
        agency_id = uuid.UUID(authenticated_client.get("/api/agency").json()["id"])
        _seed_conversation(agency_id=agency_id, client_id=customer["id"], agent_id=agent["id"])

        _suspender(authenticated_client, customer["id"])
        _reactivar(authenticated_client, customer["id"])

        portal = TestClient(authenticated_client.app)
        login = portal.post(
            f"/api/portal/{customer['portal_slug']}/login",
            json={"email": "ada@panaderia.com", "password": PASSWORD},
        )
        assert login.status_code == 200

        conversaciones = portal.get(f"/api/portal/{customer['portal_slug']}/conversations")
        assert conversaciones.status_code == 200
        assert len(conversaciones.json()) == 1


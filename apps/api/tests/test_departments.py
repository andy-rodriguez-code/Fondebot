import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Conversation

from app.routers import whatsapp_cloud_webhook as webhook_router
from app.services import ai as ai_service
from app.services import departments as departments_service
from app.services import whatsapp_inbound as whatsapp_inbound_service


APP_SECRET = "meta-app-secret"
PASSWORD = "una-contrasena-larga"


def _post_signed(client: TestClient, channel_id: str, messages: list[dict]):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "111"},
                            "contacts": [],
                            "messages": messages,
                        },
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload).encode()
    return client.post(
        f"/api/public/whatsapp-cloud/channels/{channel_id}/webhook",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest(),
        },
    )


def _text(body: str, message_id: str) -> dict:
    return {"from": "5730011", "id": message_id, "type": "text", "text": {"body": body}}


def _button(payload_id: str, title: str, message_id: str) -> dict:
    return {
        "from": "5730011",
        "id": message_id,
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": payload_id, "title": title}},
    }


def _make_agent(client: TestClient, client_id: str, name: str) -> dict:
    return client.post(
        "/api/agents",
        json={
            "client_id": client_id,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "name": name,
            "description": "",
            "instructions": "",
            "personality": "",
            "is_active": True,
        },
    ).json()


def _quiet_channel(monkeypatch, *, reply: str = "hola") -> AsyncMock:
    """Silence every outbound call and return the interactive-menu spy."""
    monkeypatch.setattr(
        whatsapp_inbound_service, "run_completion", AsyncMock(return_value=ai_service.Completion(text=reply))
    )
    monkeypatch.setattr(webhook_router, "send_text", AsyncMock(return_value="wamid.out"))
    monkeypatch.setattr(whatsapp_inbound_service, "mark_read_with_typing", AsyncMock())
    monkeypatch.setattr(whatsapp_inbound_service.get_settings(), "reply_debounce_seconds", 0)
    send_buttons = AsyncMock(return_value="wamid.menu")
    monkeypatch.setattr(departments_service, "send_buttons", send_buttons)
    return send_buttons


NAMES = {"Recepción": "Recepcion", "Tesorería": "Tesoreria", "Contabilidad": "Contabilidad"}


def _setup(client: TestClient) -> dict:
    """A client with a Cloud API channel, a portal, and three departments."""
    customer = client.post(
        "/api/clients",
        json={"name": "Fondo", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    client.put("/api/providers/openai", json={"api_key": "secret"})
    agents = {name: _make_agent(client, customer["id"], name) for name in NAMES.values()}
    channel = client.put(
        f"/api/whatsapp-cloud/channels/{customer['id']}",
        json={
            "agent_id": agents["Recepcion"]["id"],
            "phone_number_id": "111",
            "waba_id": "waba-1",
            "access_token": "meta-access-token",
            "app_secret": APP_SECRET,
        },
    ).json()
    departments = {}
    for position, (name, is_entry) in enumerate(
        [("Recepción", True), ("Tesorería", False), ("Contabilidad", False)]
    ):
        created = client.post(
            f"/api/clients/{customer['id']}/departments",
            json={"name": name, "agent_id": agents[NAMES[name]]["id"], "is_entry": is_entry, "position": position},
        )
        assert created.status_code == 201, created.text
        departments[name] = created.json()
    # The portal is not enabled here: `update_client_portal` refuses to publish
    # a portal nobody can sign in to (clients.py:148), so the tests that need it
    # enable it themselves once they have created a portal user.
    customer = client.get(f"/api/clients/{customer['id']}").json()
    return {"customer": customer, "agents": agents, "channel": channel, "departments": departments}


def _enable_portal(client: TestClient, customer_id: str) -> dict:
    published = client.patch(f"/api/clients/{customer_id}/portal", json={"portal_enabled": True})
    assert published.status_code == 200, published.text
    return published.json()


def _conversation(client: TestClient) -> dict:
    rows = client.get("/api/conversations").json()
    assert len(rows) == 1
    return rows[0]


def _portal_client(app, customer: dict, email: str) -> TestClient:
    portal = TestClient(app)
    signed_in = portal.post(
        f"/api/portal/{customer['portal_slug']}/login", json={"email": email, "password": PASSWORD}
    )
    assert signed_in.status_code == 200, signed_in.text
    return portal


# --- CRUD -------------------------------------------------------------------


def test_first_department_becomes_the_entry_one(authenticated_client: TestClient):
    client = authenticated_client
    customer = client.post(
        "/api/clients",
        json={"name": "Fondo", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    client.put("/api/providers/openai", json={"api_key": "secret"})
    agent = _make_agent(client, customer["id"], "Uno")
    created = client.post(
        f"/api/clients/{customer['id']}/departments", json={"name": "Recaudo", "agent_id": agent["id"]}
    ).json()
    assert created["is_entry"] is True
    assert created["slug"] == "recaudo"
    assert created["agent_name"] == "Uno"


def test_department_agent_must_belong_to_the_client(authenticated_client: TestClient):
    client = authenticated_client
    setup = _setup(client)
    other = client.post(
        "/api/clients",
        json={"name": "Otro", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    foreign_agent = _make_agent(client, other["id"], "Ajeno")
    rejected = client.post(
        f"/api/clients/{setup['customer']['id']}/departments",
        json={"name": "Legal", "agent_id": foreign_agent["id"]},
    )
    assert rejected.status_code == 422
    assert "does not belong" in rejected.json()["detail"]


def test_only_one_entry_department_at_a_time(authenticated_client: TestClient):
    client = authenticated_client
    setup = _setup(client)
    customer_id = setup["customer"]["id"]
    promoted = client.patch(
        f"/api/clients/{customer_id}/departments/{setup['departments']['Tesorería']['id']}",
        json={"is_entry": True},
    )
    assert promoted.status_code == 200, promoted.text
    entries = [row for row in client.get(f"/api/clients/{customer_id}/departments").json() if row["is_entry"]]
    assert [row["name"] for row in entries] == ["Tesorería"]


def test_the_entry_department_cannot_be_left_vacant(authenticated_client: TestClient):
    client = authenticated_client
    setup = _setup(client)
    customer_id = setup["customer"]["id"]
    entry_id = setup["departments"]["Recepción"]["id"]
    assert client.patch(f"/api/clients/{customer_id}/departments/{entry_id}", json={"is_entry": False}).status_code == 422
    assert client.delete(f"/api/clients/{customer_id}/departments/{entry_id}").status_code == 422


# --- Choice matching (pure) -------------------------------------------------


def test_match_choice_is_exact_on_purpose():
    rows = [
        SimpleNamespace(name="Tesorería", slug="tesoreria"),
        SimpleNamespace(name="Contabilidad", slug="contabilidad"),
    ]
    # A sentence that merely names a department is not a choice — otherwise
    # "no quiero nada con tesorería" would route straight to treasury.
    assert departments_service.match_choice(rows, text="no quiero nada con tesorería") is None
    assert departments_service.match_choice(rows, text="TESORERIA").name == "Tesorería"
    assert departments_service.match_choice(rows, text=" tesorería ").name == "Tesorería"
    assert departments_service.match_choice(rows, text="2").name == "Contabilidad"
    assert departments_service.match_choice(rows, text="9") is None
    assert departments_service.match_choice(rows, text="") is None
    assert departments_service.match_choice(rows, payload="dept:contabilidad").name == "Contabilidad"
    assert departments_service.match_choice(rows, payload="dept:ventas") is None


# --- Entry menu and routing -------------------------------------------------


def test_first_message_gets_the_menu_and_no_ai_reply(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    setup = _setup(client)
    send_buttons = _quiet_channel(monkeypatch, reply="no debería contestar")

    assert _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")]).status_code == 200

    whatsapp_inbound_service.run_completion.assert_not_awaited()
    send_buttons.assert_awaited_once()
    options = send_buttons.await_args.args[4]
    assert [title for _payload, title in options] == ["Recepción", "Tesorería", "Contabilidad"]
    assert [payload for payload, _title in options] == ["dept:recepcion", "dept:tesoreria", "dept:contabilidad"]
    # The case starts in reception, so it is never left without an owner.
    assert _conversation(client)["department_id"] == setup["departments"]["Recepción"]["id"]


def test_the_menu_is_offered_once_per_conversation(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    setup = _setup(client)
    send_buttons = _quiet_channel(monkeypatch)

    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _post_signed(client, setup["channel"]["id"], [_text("¿me ayudan?", "wamid.2")])

    assert send_buttons.await_count == 1
    # Free text leaves the case in reception, answered by reception's agent.
    conversation = _conversation(client)
    assert conversation["department_id"] == setup["departments"]["Recepción"]["id"]
    assert conversation["agent_id"] == setup["agents"]["Recepcion"]["id"]


def test_tapping_a_button_routes_the_conversation(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    setup = _setup(client)
    _quiet_channel(monkeypatch)

    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _post_signed(client, setup["channel"]["id"], [_button("dept:tesoreria", "Tesorería", "wamid.2")])

    conversation = _conversation(client)
    assert conversation["department_id"] == setup["departments"]["Tesorería"]["id"]
    # The agent answering changes with the department.
    assert conversation["agent_id"] == setup["agents"]["Tesoreria"]["id"]

    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    routed = [m for m in detail["messages"] if (m.get("activity") or {}).get("event") == "routed"]
    assert len(routed) == 1
    assert routed[0]["activity"]["department"] == "Tesorería"


def test_replying_with_the_menu_number_routes_too(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    setup = _setup(client)
    _quiet_channel(monkeypatch)

    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _post_signed(client, setup["channel"]["id"], [_text("3", "wamid.2")])

    assert _conversation(client)["department_id"] == setup["departments"]["Contabilidad"]["id"]


def test_a_reception_out_of_the_menu_still_answers(authenticated_client: TestClient, monkeypatch):
    """Answering and being in the menu are separate.

    Taking reception out of the menu is how a client offers exactly its real
    departments as buttons while something still replies before the choice.
    """
    client = authenticated_client
    setup = _setup(client)
    customer_id = setup["customer"]["id"]
    hidden = client.patch(
        f"/api/clients/{customer_id}/departments/{setup['departments']['Recepción']['id']}",
        json={"enabled": False},
    )
    assert hidden.status_code == 200, hidden.text
    send_buttons = _quiet_channel(monkeypatch)

    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])

    options = send_buttons.await_args.args[4]
    assert [title for _payload, title in options] == ["Tesorería", "Contabilidad"]
    # It is still the department holding the case, and its agent is the one
    # that answers once the contact writes without choosing.
    conversation = _conversation(client)
    assert conversation["department_id"] == setup["departments"]["Recepción"]["id"]
    assert conversation["agent_id"] == setup["agents"]["Recepcion"]["id"]

    # Positions follow the menu, so "1" is now the first offered department.
    _post_signed(client, setup["channel"]["id"], [_text("1", "wamid.2")])
    assert _conversation(client)["department_id"] == setup["departments"]["Tesorería"]["id"]


def test_a_client_without_departments_is_untouched(authenticated_client: TestClient, monkeypatch):
    """The menu only exists for clients that opted into departments."""
    client = authenticated_client
    customer = client.post(
        "/api/clients",
        json={"name": "Bistro", "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()
    client.put("/api/providers/openai", json={"api_key": "secret"})
    agent = _make_agent(client, customer["id"], "Host")
    channel = client.put(
        f"/api/whatsapp-cloud/channels/{customer['id']}",
        json={
            "agent_id": agent["id"],
            "phone_number_id": "111",
            "waba_id": "waba-1",
            "access_token": "meta-access-token",
            "app_secret": APP_SECRET,
        },
    ).json()
    send_buttons = _quiet_channel(monkeypatch, reply="Bienvenido")

    _post_signed(client, channel["id"], [_text("Hola", "wamid.1")])

    send_buttons.assert_not_awaited()
    whatsapp_inbound_service.run_completion.assert_awaited()
    assert _conversation(client)["department_id"] is None


# --- Portal boundary --------------------------------------------------------


def test_a_person_only_sees_their_own_department(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    setup = _setup(client)
    customer = setup["customer"]
    created = client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={
            "email": "tesoreria@fondo.com",
            "password": PASSWORD,
            "name": "Tesa",
            "department_id": setup["departments"]["Tesorería"]["id"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["department_name"] == "Tesorería"
    customer = _enable_portal(client, customer["id"])

    _quiet_channel(monkeypatch)
    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _post_signed(client, setup["channel"]["id"], [_button("dept:contabilidad", "Contabilidad", "wamid.2")])
    accounting = _conversation(client)["id"]

    portal = _portal_client(client.app, customer, "tesoreria@fondo.com")
    slug = customer["portal_slug"]
    assert portal.get(f"/api/portal/{slug}/conversations").json() == []
    assert portal.get(f"/api/portal/{slug}/conversations/summary").json()["open"] == 0
    # Pasting the id must not get around it either.
    assert portal.get(f"/api/portal/{slug}/conversations/{accounting}").status_code == 404
    assert portal.post(f"/api/portal/{slug}/conversations/{accounting}/read").status_code == 404
    assert portal.patch(f"/api/portal/{slug}/conversations/{accounting}/mode", json={"mode": "human"}).status_code == 404


def test_a_person_without_a_department_sees_everything(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    setup = _setup(client)
    customer = setup["customer"]
    client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "jefa@fondo.com", "password": PASSWORD, "name": "Jefa"},
    )
    customer = _enable_portal(client, customer["id"])

    _quiet_channel(monkeypatch)
    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _post_signed(client, setup["channel"]["id"], [_button("dept:contabilidad", "Contabilidad", "wamid.2")])

    portal = _portal_client(client.app, customer, "jefa@fondo.com")
    listed = portal.get(f"/api/portal/{customer['portal_slug']}/conversations").json()
    assert len(listed) == 1
    assert listed[0]["department_name"] == "Contabilidad"


def test_members_and_assignment_stay_inside_the_department(authenticated_client: TestClient, monkeypatch):
    client = authenticated_client
    setup = _setup(client)
    customer = setup["customer"]
    for email, department in [
        ("tesoreria@fondo.com", "Tesorería"),
        ("contabilidad@fondo.com", "Contabilidad"),
    ]:
        client.post(
            f"/api/clients/{customer['id']}/portal-users",
            json={
                "email": email,
                "password": PASSWORD,
                "name": email.split("@")[0],
                "department_id": setup["departments"][department]["id"],
            },
        )
    customer = _enable_portal(client, customer["id"])

    _quiet_channel(monkeypatch)
    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _post_signed(client, setup["channel"]["id"], [_button("dept:tesoreria", "Tesorería", "wamid.2")])
    conversation_id = _conversation(client)["id"]

    portal = _portal_client(client.app, customer, "tesoreria@fondo.com")
    slug = customer["portal_slug"]
    members = portal.get(f"/api/portal/{slug}/members").json()
    assert [m["email"] for m in members] == ["tesoreria@fondo.com"]

    accounting_id = next(
        row["id"]
        for row in client.get(f"/api/clients/{customer['id']}/portal-users").json()
        if row["email"] == "contabilidad@fondo.com"
    )
    handed_away = portal.post(
        f"/api/portal/{slug}/conversations/{conversation_id}/assignment", json={"assignee_id": accounting_id}
    )
    assert handed_away.status_code == 404


# --- Conversaciones anteriores a las dependencias ---------------------------
#
# Estado real encontrado en una instalacion: un caso abierto ANTES de que el
# cliente cargara sus dependencias queda con `department_id` nulo. Eso no es un
# estado neutro, y rompe dos cosas a la vez.


def _orphan_the_conversation() -> None:
    """Deja el caso sin dependencia, como quedan los anteriores a la funcion."""
    with SessionLocal() as db:
        row = db.scalars(select(Conversation)).one()
        row.department_id = None
        db.commit()


def test_a_conversation_without_a_department_adopts_reception(authenticated_client: TestClient, monkeypatch):
    """Sin esto el caso es invisible para todo el mundo.

    ``_visible`` filtra por igualdad, y un nulo no coincide con ninguna
    dependencia: quien pertenece a una no ve el caso, asi que nadie lo puede
    contestar desde el portal. No es que falte un permiso — no aparece.
    """
    client = authenticated_client
    setup = _setup(client)
    _quiet_channel(monkeypatch)
    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _orphan_the_conversation()

    _post_signed(client, setup["channel"]["id"], [_text("sigo ahi?", "wamid.2")])

    conversation = _conversation(client)
    assert conversation["department_id"] == setup["departments"]["Recepción"]["id"]
    assert conversation["agent_id"] == setup["agents"]["Recepcion"]["id"]


def test_choosing_from_the_menu_works_without_a_department(authenticated_client: TestClient, monkeypatch):
    """El sintoma que se ve desde afuera: elegir no hacia nada.

    El texto solo contaba como eleccion estando en recepcion, y un caso sin
    dependencia no estaba en recepcion. Recibia el menu, el contacto escribia
    "3", y le contestaba la IA como si nada. Para siempre.
    """
    client = authenticated_client
    setup = _setup(client)
    _quiet_channel(monkeypatch)
    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _orphan_the_conversation()

    _post_signed(client, setup["channel"]["id"], [_text("3", "wamid.2")])

    assert _conversation(client)["department_id"] == setup["departments"]["Contabilidad"]["id"]


# Un caso por test y no dos mensajes en el mismo: el canal de prueba devuelve
# siempre el mismo id de mensaje saliente, y dos respuestas en una conversacion
# chocan contra `uq_messages_conversation_external`.


def test_a_number_outside_the_menu_does_not_route(authenticated_client: TestClient, monkeypatch):
    """Lo que NO tiene que pasar: entrar a cualquier lado.

    Que un caso sin dependencia pueda elegir no significa que cualquier cosa
    sirva. Fuera del menu se queda en recepcion.
    """
    client = authenticated_client
    setup = _setup(client)
    _quiet_channel(monkeypatch)
    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _orphan_the_conversation()

    _post_signed(client, setup["channel"]["id"], [_text("9", "wamid.2")])
    assert _conversation(client)["department_id"] == setup["departments"]["Recepción"]["id"]


def test_naming_a_department_in_a_sentence_does_not_route(authenticated_client: TestClient, monkeypatch):
    """Nombrar una dependencia al pasar no es elegirla.

    La coincidencia es exacta a proposito, y eso tiene que seguir valiendo
    tambien para un caso que llego sin dependencia.
    """
    client = authenticated_client
    setup = _setup(client)
    _quiet_channel(monkeypatch)
    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _orphan_the_conversation()

    _post_signed(client, setup["channel"]["id"], [_text("no quiero nada con contabilidad", "wamid.2")])
    assert _conversation(client)["department_id"] == setup["departments"]["Recepción"]["id"]


# --- El bot es una opcion, no un requisito ----------------------------------


def test_without_a_usable_agent_the_case_goes_to_a_person(authenticated_client: TestClient, monkeypatch):
    """Lo que pasa cuando no hay clave de proveedor cargada.

    El menu de dependencias y el ruteo no necesitan IA: son codigo. Pero si el
    agente de la dependencia no puede contestar, el caso tiene que pasar a una
    persona. Antes se quedaba en modo "ai" y el motivo solo figuraba en la
    pantalla del canal, en el panel del admin: en el portal aparecia como
    atendida por el bot, la dependencia no se enteraba, y quien escribio no
    recibia respuesta de nadie.
    """
    client = authenticated_client
    setup = _setup(client)
    _quiet_channel(monkeypatch)
    # Sin modelo, el agente no puede contestar aunque haya credenciales.
    agent_id = setup["agents"]["Recepcion"]["id"]
    assert client.patch(f"/api/agents/{agent_id}", json={"model": ""}).status_code == 200

    _post_signed(client, setup["channel"]["id"], [_text("Hola", "wamid.1")])
    _post_signed(client, setup["channel"]["id"], [_text("necesito ayuda", "wamid.2")])

    conversation = _conversation(client)
    assert conversation["mode"] == "human", "el caso tiene que quedar esperando a una persona"
    assert conversation["status"] == "open"

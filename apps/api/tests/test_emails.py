"""The outbound e-mail seam and the invitation body it composes.

There is no HTTP endpoint sending these yet, so the composition is exercised
directly. What matters here is that a built message is actually deliverable and
reads in Spanish to the person receiving it.
"""

import uuid

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Client, Department
from app.services import emails as emails_service
from app.services.emails import Email, build_invitation_email


def _make_client(client: TestClient, name: str = "Cliente Demo") -> dict:
    return client.post(
        "/api/clients",
        json={"name": name, "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()


def _make_department(client: TestClient, client_id: str, name: str = "Soporte") -> dict:
    client.put("/api/providers/openai", json={"api_key": "secret"})
    agent = client.post(
        "/api/agents",
        json={
            "client_id": client_id,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "name": "Agente",
            "description": "",
            "instructions": "",
            "personality": "",
            "is_active": True,
        },
    ).json()
    created = client.post(
        f"/api/clients/{client_id}/departments",
        json={"name": name, "agent_id": agent["id"], "is_entry": True, "position": 0},
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_the_default_provider_sends_nothing_and_says_so():
    # A self-hosted install with no SMTP must still be able to create an
    # invitation; the caller reads this to decide whether to hand the link back
    # to the admin instead.
    assert emails_service.configured_provider() == "none"
    assert emails_service.email_enabled() is False
    assert "none" in emails_service.available_providers()
    assert "smtp" in emails_service.available_providers()


def test_an_unknown_provider_falls_back_to_sending_nothing(monkeypatch):
    settings = emails_service.get_settings().model_copy(update={"email_provider": "typo-smpt"})
    monkeypatch.setattr(emails_service, "get_settings", lambda: settings)
    # A typo in an environment variable must leave delivery off, not break the
    # request that was only trying to create an invitation.
    assert emails_service.configured_provider() == "none"
    emails_service.send_email(Email(to="a@example.com", subject="x", body="y"))


def test_build_invitation_email_is_addressed_spanish_and_carries_the_link(authenticated_client: TestClient):
    customer = _make_client(authenticated_client, name="Fondos del Pueblo")
    department_out = _make_department(authenticated_client, customer["id"], name="Soporte")
    accept_url = "https://example.com/portal/fondos-del-pueblo/invite?token=abc123"

    with SessionLocal() as db:
        client_row = db.get(Client, uuid.UUID(customer["id"]))
        department_row = db.get(Department, uuid.UUID(department_out["id"]))

        email = build_invitation_email("invitada@example.com", client_row, department_row, accept_url)

    # The recipient is the assertion that matters most: an Email with a blank
    # `to` is handed to the provider without raising and arrives nowhere.
    assert email.to == "invitada@example.com"
    assert email.subject
    # Spanish, not English: this copy is composed in the backend and never goes
    # through apps/web/lib/i18n, so assert on actual Spanish words.
    assert "invitación" in email.subject.lower() or "invitacion" in email.subject.lower()
    assert "Fondos del Pueblo" in email.body
    assert "Soporte" in email.body
    assert accept_url in email.body


def test_a_client_without_a_department_still_gets_a_readable_body(authenticated_client: TestClient):
    customer = _make_client(authenticated_client, name="Fondos del Pueblo")
    with SessionLocal() as db:
        client_row = db.get(Client, uuid.UUID(customer["id"]))
        email = build_invitation_email("invitada@example.com", client_row, None, "https://example.com/x")
    assert "None" not in email.body

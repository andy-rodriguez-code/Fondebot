"""Invitation tokens: single-use, hashed at rest, never the plaintext.

PR1 laid only the storage foundation (table, model, token helpers). This slice
adds the HTTP surface: issuing an invitation from department creation,
resending it, and the public accept endpoint — exercised through the router,
not the service layer directly, because the properties that matter here
(constant work, identical failure body, background dispatch) only exist at
that boundary.
"""

import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import app.routers.portal as portal_router
from app.config import get_settings
from app.database import SessionLocal
from app.models import Client, Conversation, PortalInvitation, PortalUser
from app.routers.portal import INVITATION_INVALID_DETAIL
from app.security import generate_invitation_token, hash_invitation_token, verify_invitation_token

PASSWORD = "una-contrasena-larga"


def _make_client(client: TestClient, name: str = "Cliente Demo") -> dict:
    return client.post(
        "/api/clients",
        json={"name": name, "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()


def _make_agent(client: TestClient, client_id: str, name: str = "Agente") -> dict:
    client.put("/api/providers/openai", json={"api_key": "secret"})
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


def _department_with_invite(
    client: TestClient, client_id: str, agent_id: str, *, invite_email: str | None, invite_name: str = ""
) -> dict:
    payload = {"name": "Soporte", "agent_id": agent_id}
    if invite_email:
        payload["invite_email"] = invite_email
        payload["invite_name"] = invite_name
    response = client.post(f"/api/clients/{client_id}/departments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _token_from_accept_url(accept_url: str) -> str:
    return parse_qs(urlparse(accept_url).query)["token"][0]


def _accept(client: TestClient, slug: str, token: str, password: str = PASSWORD):
    return client.post(f"/api/portal/{slug}/invitations/accept", json={"token": token, "password": password})


def test_token_is_urlsafe_and_hashed_at_rest(authenticated_client: TestClient):
    customer = _make_client(authenticated_client)

    raw_token = generate_invitation_token()
    # secrets.token_urlsafe(32) always yields 43 base64url characters for 32
    # random bytes (no padding).
    assert len(raw_token) == 43

    token_hash = hash_invitation_token(raw_token)
    assert len(token_hash) == 64
    int(token_hash, 16)  # raises ValueError if this is not hex

    with SessionLocal() as db:
        invitation = PortalInvitation(
            client_id=uuid.UUID(customer["id"]),
            department_id=None,
            email="invitada@example.com",
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.add(invitation)
        db.commit()

        # The raw token is never persisted: nothing in the table matches it,
        # only its digest does.
        assert db.query(PortalInvitation).filter(PortalInvitation.token_hash == raw_token).first() is None
        stored = db.query(PortalInvitation).filter(PortalInvitation.token_hash == token_hash).first()
        assert stored is not None
        assert stored.email == "invitada@example.com"

    assert verify_invitation_token(raw_token, token_hash) is True
    assert verify_invitation_token("un-token-distinto-cualquiera", token_hash) is False


# --- RED-first guards --------------------------------------------------------
#
# These two are written BEFORE the property they guard is wired, and stay
# first in this file for the same reason: a test written after the code
# already works proves nothing about either property — it would pass against
# a broken implementation just as easily. Both were red against the router
# before tasks 2.4/2.6 existed.


def test_accept_pays_the_password_hashing_cost_on_every_path(authenticated_client: TestClient, monkeypatch):
    """D3: ``hash_password`` must run even for a token that never existed.

    Hashing only on the success path turns the endpoint into a stopwatch: the
    response time alone would tell an attacker whether a token is real. A wall
    clock is not a reliable assertion in CI, so this spies on the call
    instead — the honest proxy the design document names for this guarantee.
    """
    client = authenticated_client
    customer = _make_client(client)

    real_hash_password = portal_router.hash_password
    calls: list[str] = []

    def _spy(password: str) -> str:
        calls.append(password)
        return real_hash_password(password)

    monkeypatch.setattr(portal_router, "hash_password", _spy)

    response = _accept(client, customer["portal_slug"], "un-token-que-nunca-existio-000000000")

    assert response.status_code == 400
    assert calls == ["una-contrasena-larga"]


def test_smtp_provider_is_dispatched_through_background_tasks(authenticated_client: TestClient, monkeypatch):
    """``smtplib`` must never run on the event loop (Constraint: smtplib async
    ban). ``asyncio.get_running_loop()`` only raises ``RuntimeError`` when the
    calling thread has no running loop — proof this ran on a worker thread via
    ``BackgroundTasks``, not inline inside the ``async def`` route.
    """
    import asyncio

    from app.services import emails as emails_service

    ran_off_the_loop = {"value": False}

    def _fake_smtp(email: emails_service.Email) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            ran_off_the_loop["value"] = True

    monkeypatch.setattr(emails_service, "configured_provider", lambda: "smtp")
    monkeypatch.setattr(emails_service, "_PROVIDERS", {"smtp": _fake_smtp, "none": emails_service._send_none})

    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="smtp@example.com")

    assert department["invitation"]["delivery"] == "sent"
    assert department["invitation"]["accept_url"] is None
    assert ran_off_the_loop["value"] is True


# --- Department creation ------------------------------------------------------


def test_department_create_without_email_creates_no_invitation(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])

    department = _department_with_invite(client, customer["id"], agent["id"], invite_email=None)

    assert department["invitation"] is None
    with SessionLocal() as db:
        assert db.query(PortalInvitation).count() == 0


def test_department_create_with_email_returns_manual_link_when_provider_is_none(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])

    department = _department_with_invite(
        client, customer["id"], agent["id"], invite_email="invitada@example.com", invite_name="Invitada"
    )

    invitation = department["invitation"]
    assert invitation["email"] == "invitada@example.com"
    assert invitation["delivery"] == "manual"
    assert invitation["accept_url"] is not None
    assert f"/portal/{customer['portal_slug']}/invite?token=" in invitation["accept_url"]


def test_inviting_an_existing_active_portal_user_returns_409(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    created = client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "miembro@example.com", "password": PASSWORD, "name": "Miembro"},
    )
    assert created.status_code == 201, created.text

    conflict = client.post(
        f"/api/clients/{customer['id']}/departments",
        json={"name": "Otra dependencia", "agent_id": agent["id"], "invite_email": "miembro@example.com"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "That e-mail is already on this portal"

    # Same address on a DIFFERENT client is allowed: uq_portal_users_client_email
    # is scoped per client (Spec: Duplicate Portal-User Handling).
    other = _make_client(client, "Otro cliente")
    other_agent = _make_agent(client, other["id"])
    allowed = client.post(
        f"/api/clients/{other['id']}/departments",
        json={"name": "Soporte", "agent_id": other_agent["id"], "invite_email": "miembro@example.com"},
    )
    assert allowed.status_code == 201, allowed.text


def test_only_one_pending_invitation_per_email_per_client(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent_a = _make_agent(client, customer["id"], "Uno")
    agent_b = _make_agent(client, customer["id"], "Dos")

    _department_with_invite(client, customer["id"], agent_a["id"], invite_email="doble@example.com")
    second = client.post(
        f"/api/clients/{customer['id']}/departments",
        json={"name": "Otra dependencia", "agent_id": agent_b["id"], "invite_email": "doble@example.com"},
    )
    assert second.status_code == 201, second.text

    with SessionLocal() as db:
        rows = (
            db.query(PortalInvitation)
            .filter(PortalInvitation.client_id == uuid.UUID(customer["id"]), PortalInvitation.email == "doble@example.com")
            .all()
        )
        assert len(rows) == 1
        assert str(rows[0].department_id) == second.json()["id"]


def test_reinviting_invalidates_the_previous_link(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="reinvitada@example.com")
    old_token = _token_from_accept_url(department["invitation"]["accept_url"])

    resent = client.post(f"/api/clients/{customer['id']}/departments/{department['id']}/invitations")
    assert resent.status_code == 201, resent.text
    new_token = _token_from_accept_url(resent.json()["accept_url"])
    assert new_token != old_token

    assert _accept(client, customer["portal_slug"], old_token).status_code == 400
    assert _accept(client, customer["portal_slug"], new_token).status_code == 200


# --- Accepting an invitation ---------------------------------------------------


def test_accept_creates_portal_user_scoped_to_the_department(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="nueva@example.com")
    token = _token_from_accept_url(department["invitation"]["accept_url"])

    accepted = _accept(client, customer["portal_slug"], token)
    assert accepted.status_code == 200, accepted.text

    with SessionLocal() as db:
        portal_user = db.query(PortalUser).filter(PortalUser.email == "nueva@example.com").one()
        assert str(portal_user.client_id) == customer["id"]
        assert str(portal_user.department_id) == department["id"]
        assert portal_user.is_active is True
        invitation = db.get(PortalInvitation, uuid.UUID(department["invitation"]["id"]))
        assert invitation.accepted_at is not None


def test_accept_sets_the_portal_cookie_and_returns_a_session(authenticated_client: TestClient):
    """The session an accept hands back only opens a portal that is published.

    So this models inviting the *second* person: a portal cannot be published
    until it has someone who can sign in, and that first someone is created by
    accepting an invitation. Asserting a working session on a client whose
    portal was never enabled would be asserting something the product does not
    promise — `_portal_client` refuses an unpublished portal, and rightly so.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "primera@example.com", "password": PASSWORD, "name": "Primera"},
    )
    published = client.patch(f"/api/clients/{customer['id']}/portal", json={"portal_enabled": True})
    assert published.status_code == 200, published.text

    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="sesion@example.com")
    token = _token_from_accept_url(department["invitation"]["accept_url"])

    accepted = _accept(client, customer["portal_slug"], token)
    assert accepted.status_code == 200
    assert accepted.json()["user_id"] is not None
    assert "portal_access_token" in accepted.cookies

    me = client.get(f"/api/portal/{customer['portal_slug']}/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == accepted.json()["user_id"]


def test_accept_works_before_the_portal_is_published(authenticated_client: TestClient):
    """The first person in has to be able to accept, or nothing ever starts.

    Publishing a portal requires an active user and the only way to get one is
    to accept an invitation, so requiring a published portal here would
    deadlock the whole flow. The account is created and the invitation burned;
    the session it returns simply opens nothing until an admin publishes.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="primera@example.com")
    token = _token_from_accept_url(department["invitation"]["accept_url"])

    assert _accept(client, customer["portal_slug"], token).status_code == 200
    with SessionLocal() as db:
        assert db.query(PortalUser).filter(PortalUser.email == "primera@example.com").one().is_active is True

    # And now the portal can be published, which it could not be a moment ago.
    published = client.patch(f"/api/clients/{customer['id']}/portal", json={"portal_enabled": True})
    assert published.status_code == 200, published.text


def test_accept_is_single_use(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="unica@example.com")
    token = _token_from_accept_url(department["invitation"]["accept_url"])

    assert _accept(client, customer["portal_slug"], token).status_code == 200
    second = _accept(client, customer["portal_slug"], token, password="otra-contrasena-larga")
    assert second.status_code == 400
    assert second.json()["detail"] == INVITATION_INVALID_DETAIL


def test_accept_refuses_an_expired_token(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="vencida@example.com")
    token = _token_from_accept_url(department["invitation"]["accept_url"])

    with SessionLocal() as db:
        invitation = db.get(PortalInvitation, uuid.UUID(department["invitation"]["id"]))
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    expired = _accept(client, customer["portal_slug"], token)
    assert expired.status_code == 400
    assert expired.json()["detail"] == INVITATION_INVALID_DETAIL


def test_accept_returns_the_same_body_for_unknown_expired_and_burned_tokens(authenticated_client: TestClient):
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])

    unknown = _accept(client, customer["portal_slug"], "un-token-que-nunca-existio-123456789")

    expired_dept = _department_with_invite(client, customer["id"], agent["id"], invite_email="vencida2@example.com")
    expired_token = _token_from_accept_url(expired_dept["invitation"]["accept_url"])
    with SessionLocal() as db:
        row = db.get(PortalInvitation, uuid.UUID(expired_dept["invitation"]["id"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    expired = _accept(client, customer["portal_slug"], expired_token)

    burned_dept = _department_with_invite(client, customer["id"], agent["id"], invite_email="quemada@example.com")
    burned_token = _token_from_accept_url(burned_dept["invitation"]["accept_url"])
    assert _accept(client, customer["portal_slug"], burned_token).status_code == 200
    burned = _accept(client, customer["portal_slug"], burned_token, password="otra-contrasena-larga")

    for response in (unknown, expired, burned):
        assert response.status_code == 400
        assert response.json() == {"detail": INVITATION_INVALID_DETAIL}


def test_accept_rejects_an_overlong_password_instead_of_crashing(authenticated_client: TestClient):
    """bcrypt raises above 72 bytes, and hashing runs before the token check.

    Without the schema guard, a long password reaches `hash_password` as the
    first statement of a public, unauthenticated handler and becomes a 500 —
    whatever the token was. 422 is the honest answer, and rejecting on length
    alone leaks nothing the sender did not already know.
    """
    client = authenticated_client
    customer = _make_client(client)

    # Accented characters are two bytes each: 40 of them exceed 72 bytes while
    # staying well under the 128-character cap.
    long_password = "á" * 40
    assert len(long_password) < 128
    assert len(long_password.encode()) > 72

    response = _accept(client, customer["portal_slug"], "cualquier-token", password=long_password)
    assert response.status_code == 422


def test_accept_rejects_a_token_from_another_portal_slug(authenticated_client: TestClient):
    client = authenticated_client
    customer_a = _make_client(client, "Cliente A")
    customer_b = _make_client(client, "Cliente B")
    agent_a = _make_agent(client, customer_a["id"])
    department = _department_with_invite(client, customer_a["id"], agent_a["id"], invite_email="cruzada@example.com")
    token = _token_from_accept_url(department["invitation"]["accept_url"])

    wrong_slug = _accept(client, customer_b["portal_slug"], token)
    assert wrong_slug.status_code == 400
    assert wrong_slug.json()["detail"] == INVITATION_INVALID_DETAIL


# --- Delivery outcome (D7) ----------------------------------------------------


def test_email_delivery_failure_is_recorded_on_the_invitation(authenticated_client: TestClient, monkeypatch):
    """D7: a background send that fails must not read back as "sent" by silence.

    ``send_invitation_email`` (``services/invitations.py``) wraps the actual
    delivery, catches any exception and writes ``delivery_error`` on the row;
    a later ``GET /clients/{id}/departments`` read must then report
    ``delivery == "failed"`` instead of repeating the create-time optimistic
    guess. The fake provider raises synchronously, and this test suite's
    ``TestClient`` runs ``BackgroundTasks`` inline before the HTTP call
    returns (see ``test_smtp_provider_is_dispatched_through_background_tasks``
    above), so the failure is already recorded by the time this test reads it
    back.
    """
    from app.services import emails as emails_service

    def _boom(_email: emails_service.Email) -> None:
        raise smtplib.SMTPException("Connection refused")

    monkeypatch.setattr(emails_service, "configured_provider", lambda: "smtp")
    monkeypatch.setattr(emails_service, "_PROVIDERS", {"smtp": _boom, "none": emails_service._send_none})

    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="rebota@example.com")

    with SessionLocal() as db:
        invitation = db.get(PortalInvitation, uuid.UUID(department["invitation"]["id"]))
        assert invitation.delivery_error is not None
        assert "Connection refused" in invitation.delivery_error
        assert invitation.delivered_at is None

    listing = client.get(f"/api/clients/{customer['id']}/departments")
    assert listing.status_code == 200, listing.text
    read_department = next(row for row in listing.json() if row["id"] == department["id"])
    assert read_department["invitation"]["delivery"] == "failed"
    assert read_department["invitation"]["accept_url"] is None


# --- D5: deleting a department cascades to its pending invitation ------------


def test_deleting_the_department_removes_its_pending_invitation(authenticated_client: TestClient):
    """``department_id`` is CASCADE (D5), unlike ``portal_users``/``conversations``
    which use SET NULL: a deleted department must not silently promote a
    department-scoped pending invite into a client-wide one.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent_a = _make_agent(client, customer["id"], "Uno")
    agent_b = _make_agent(client, customer["id"], "Dos")
    # The first department created becomes the entry one automatically, so a
    # second, non-entry department is what gets the invite and gets deleted —
    # deleting the sole/entry department is rejected for an unrelated reason.
    client.post(
        f"/api/clients/{customer['id']}/departments",
        json={"name": "Recepción", "agent_id": agent_a["id"]},
    )
    department = _department_with_invite(client, customer["id"], agent_b["id"], invite_email="borrada@example.com")

    deleted = client.delete(f"/api/clients/{customer['id']}/departments/{department['id']}")
    assert deleted.status_code == 204, deleted.text

    with SessionLocal() as db:
        assert (
            db.query(PortalInvitation)
            .filter(PortalInvitation.client_id == uuid.UUID(customer["id"]))
            .count()
            == 0
        )


# --- Regressions found by verification ----------------------------------------


def test_inviting_a_suspended_portal_user_is_refused_not_deferred_to_a_500(authenticated_client: TestClient):
    """The guard has to mirror the constraint, not a friendlier subset of it.

    `uq_portal_users_client_email` does not care whether a row is active, so a
    guard that only looked at active members let the invitation through and
    moved the failure to the accept endpoint — where the INSERT hit the index
    and turned into a 500, on a public unauthenticated route. A suspended
    person already exists; the answer is to reactivate them.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    created = client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "suspendida@example.com", "password": PASSWORD, "name": "Suspendida"},
    )
    assert created.status_code == 201, created.text
    suspended = client.patch(
        f"/api/clients/{customer['id']}/portal-users/{created.json()['id']}", json={"is_active": False}
    )
    assert suspended.status_code == 200, suspended.text

    refused = client.post(
        f"/api/clients/{customer['id']}/departments",
        json={"name": "Soporte", "agent_id": agent["id"], "invite_email": "suspendida@example.com"},
    )
    assert refused.status_code == 409
    with SessionLocal() as db:
        assert db.query(PortalInvitation).count() == 0


def test_resending_after_the_address_became_a_member_is_refused(authenticated_client: TestClient):
    """Refreshing a token that can only ever collide is not a resend."""
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="doble@example.com")

    client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "doble@example.com", "password": PASSWORD, "name": "Doble"},
    )

    resent = client.post(f"/api/clients/{customer['id']}/departments/{department['id']}/invitations")
    assert resent.status_code == 409, resent.text


def test_an_admin_cannot_invite_into_another_agencys_client(client: TestClient, monkeypatch):
    """Tenant isolation, exercised rather than assumed.

    The existing wrong-slug test uses two clients of the SAME agency, so it
    reads like this one without being it.
    """
    monkeypatch.setattr(get_settings(), "allow_multi_agency", True)
    client.post(
        "/api/auth/register",
        json={"agency_name": "Agencia A", "name": "Ana", "email": "ana@a.com", "password": "una-clave-larga"},
    )
    customer = _make_client(client, "Cliente de A")
    agent = _make_agent(client, customer["id"])

    # Registering switches the session to the second agency.
    client.post(
        "/api/auth/register",
        json={"agency_name": "Agencia B", "name": "Bea", "email": "bea@b.com", "password": "otra-clave-larga"},
    )
    intruder = client.post(
        f"/api/clients/{customer['id']}/departments",
        json={"name": "Ajena", "agent_id": agent["id"], "invite_email": "objetivo@example.com"},
    )

    assert intruder.status_code == 404
    with SessionLocal() as db:
        assert db.query(PortalInvitation).count() == 0


def test_the_password_chosen_when_accepting_is_the_one_that_signs_in(authenticated_client: TestClient):
    """Without this, storing a constant hash would leave the suite green.

    Every other accept test checks columns, the cookie and /me — all of which
    hold whether or not the stored hash corresponds to what was typed.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "primera@example.com", "password": PASSWORD, "name": "Primera"},
    )
    assert client.patch(f"/api/clients/{customer['id']}/portal", json={"portal_enabled": True}).status_code == 200

    department = _department_with_invite(client, customer["id"], agent["id"], invite_email="nueva@example.com")
    chosen = "la-que-yo-elegi-1234"
    token = _token_from_accept_url(department["invitation"]["accept_url"])
    assert _accept(client, customer["portal_slug"], token, password=chosen).status_code == 200

    fresh = TestClient(client.app)
    slug = customer["portal_slug"]
    assert fresh.post(f"/api/portal/{slug}/login", json={"email": "nueva@example.com", "password": chosen}).status_code == 200
    wrong = fresh.post(f"/api/portal/{slug}/login", json={"email": "nueva@example.com", "password": PASSWORD})
    assert wrong.status_code == 401


def test_a_user_created_by_accepting_only_sees_their_own_department(authenticated_client: TestClient):
    """The spec scopes the inbox for a user *created via acceptance*.

    Asserting the department_id column, which the other accept tests do, says
    nothing about the boundary: `_visible` is what enforces it, and until now
    it was only ever exercised for users made through create_portal_user.
    """
    client = authenticated_client
    customer = _make_client(client)
    agent = _make_agent(client, customer["id"])
    client.post(
        f"/api/clients/{customer['id']}/portal-users",
        json={"email": "jefa@example.com", "password": PASSWORD, "name": "Jefa"},
    )
    assert client.patch(f"/api/clients/{customer['id']}/portal", json={"portal_enabled": True}).status_code == 200

    mine = _department_with_invite(client, customer["id"], agent["id"], invite_email="mia@example.com")
    other = client.post(
        f"/api/clients/{customer['id']}/departments",
        json={"name": "Contabilidad", "agent_id": agent["id"]},
    )
    assert other.status_code == 201, other.text

    chosen = "mi-propia-clave-9876"
    token = _token_from_accept_url(mine["invitation"]["accept_url"])
    assert _accept(client, customer["portal_slug"], token, password=chosen).status_code == 200

    # One conversation in each department, inserted directly: what is under
    # test is the read boundary, not how a conversation comes into being.
    with SessionLocal() as db:
        client_row = db.get(Client, uuid.UUID(customer["id"]))
        for department_id, title in ((mine["id"], "Caso mío"), (other.json()["id"], "Caso ajeno")):
            db.add(
                Conversation(
                    agency_id=client_row.agency_id,
                    client_id=client_row.id,
                    agent_id=uuid.UUID(agent["id"]),
                    department_id=uuid.UUID(department_id),
                    title=title,
                    channel="whatsapp_cloud",
                )
            )
        db.commit()

    portal = TestClient(client.app)
    slug = customer["portal_slug"]
    assert portal.post(f"/api/portal/{slug}/login", json={"email": "mia@example.com", "password": chosen}).status_code == 200
    titles = [row["title"] for row in portal.get(f"/api/portal/{slug}/conversations").json()]
    assert titles == ["Caso mío"]

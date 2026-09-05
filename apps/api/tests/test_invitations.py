"""Invitation tokens: single-use, hashed at rest, never the plaintext.

This slice lays only the storage foundation — the table, the model, and the
token helpers in ``app/security.py``. There is no HTTP endpoint yet (issuing,
resending and accepting land later), so these exercise the pieces directly
rather than through a router.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import PortalInvitation
from app.security import generate_invitation_token, hash_invitation_token, verify_invitation_token


def _make_client(client: TestClient, name: str = "Cliente Demo") -> dict:
    return client.post(
        "/api/clients",
        json={"name": name, "industry": "", "description": "", "general_context": "", "is_active": True},
    ).json()


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

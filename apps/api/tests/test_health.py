"""Pruebas de la Slice 2a: GET /api/health/ready y GET /api/health/errors.

Para cada una: qué se rompe si la propiedad que cubre retrocede. Ver
sdd/site-health-and-error-tracking/design (D6, D9) para el porqué de cada
guarda.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.main import app
from app.models import ErrorEvent, now_utc


# --- readiness (3.3 / 3.4 / 3.5) ---------------------------------------------


def test_readiness_is_ok_when_the_database_answers(client: TestClient):
    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_readiness_needs_no_session(client: TestClient):
    # No hay cookie de sesión seteada en ningún lado de este test: debe
    # responder igual, nunca 401 — un monitor externo no tiene sesión.
    response = client.get("/api/health/ready")
    assert response.status_code == 200


def test_liveness_is_untouched(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _BoomSession:
    """Sesión falsa cuyo ``execute`` siempre falla, para simular la base
    caída sin apagar el Postgres real de la suite."""

    def execute(self, *_args, **_kwargs):
        raise OperationalError(
            "SELECT 1", {}, Exception("could not connect to server: host=db user=openlivery")
        )

    def close(self) -> None:
        pass


@pytest.fixture
def broken_db_client(client: TestClient):
    def _override():
        db = _BoomSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield client
    app.dependency_overrides.clear()


def test_readiness_reports_degraded_without_leaking_the_reason(broken_db_client: TestClient):
    response = broken_db_client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": "error"}}
    for leaked in ("could not connect", "host=", "openlivery"):
        assert leaked not in response.text


def test_readiness_records_no_error_event(broken_db_client: TestClient):
    broken_db_client.get("/api/health/ready")

    with SessionLocal() as db:
        assert db.query(ErrorEvent).count() == 0


# --- lista de errores (3.8 / 3.9 / 3.10) -------------------------------------


def _own_agency_id(client: TestClient) -> uuid.UUID:
    return uuid.UUID(client.get("/api/auth/me").json()["agency"]["id"])


def _insert_error(*, agency_id: uuid.UUID | None, occurred_at=None) -> uuid.UUID:
    with SessionLocal() as db:
        row = ErrorEvent(
            agency_id=agency_id,
            occurred_at=occurred_at or now_utc(),
            source="http",
            capture_kind="handler",
            exception_type="RuntimeError",
            message="boom",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def test_the_list_returns_own_agency_rows_and_agency_less_rows(
    authenticated_client: TestClient, monkeypatch
):
    monkeypatch.setattr(get_settings(), "allow_multi_agency", True)
    own_agency_id = _own_agency_id(authenticated_client)

    # Su propio TestClient para no pisar la cookie de authenticated_client;
    # no se usa como context manager para no correr el lifespan de nuevo
    # (mismo motivo que lenient_client en test_error_capture.py).
    other_client = TestClient(app)
    other_client.post(
        "/api/auth/register",
        json={
            "agency_name": "Agencia Ajena",
            "name": "Bea",
            "email": "bea@ajena.com",
            "password": "otra-clave-larga",
        },
    )
    other_agency_id = _own_agency_id(other_client)
    other_client.close()

    own_row_id = _insert_error(agency_id=own_agency_id)
    global_row_id = _insert_error(agency_id=None)
    other_row_id = _insert_error(agency_id=other_agency_id)

    response = authenticated_client.get("/api/health/errors")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert {str(own_row_id), str(global_row_id)} <= ids
    assert str(other_row_id) not in ids


def test_the_list_pages_without_repeating_a_row(authenticated_client: TestClient):
    own_agency_id = _own_agency_id(authenticated_client)
    same_moment = now_utc()
    for _ in range(5):
        _insert_error(agency_id=own_agency_id, occurred_at=same_moment)

    first_page = authenticated_client.get("/api/health/errors", params={"limit": 2}).json()
    assert len(first_page) == 2

    second_page = authenticated_client.get(
        "/api/health/errors", params={"limit": 2, "before": first_page[-1]["id"]}
    ).json()
    assert len(second_page) == 2

    seen_ids = {row["id"] for row in first_page} | {row["id"] for row in second_page}
    assert len(seen_ids) == 4


def test_the_list_requires_a_session(client: TestClient):
    response = client.get("/api/health/errors")
    assert response.status_code == 401


def test_a_purged_cursor_ends_pagination_instead_of_restarting_it(authenticated_client: TestClient):
    """The purge runs hourly, and this table is paginated during the incident
    that makes the purge fire. Ignoring a vanished cursor would silently return
    the first page again, so a client walking pages would loop on it forever.
    """
    client = authenticated_client
    gone = uuid.uuid4()
    response = client.get(f"/api/health/errors?before={gone}")
    assert response.status_code == 200, response.text
    assert response.json() == []

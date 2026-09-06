"""Pruebas de app/services/error_log.py — puro/servicio, sin HTTP.

Para cada una: qué se rompe si la propiedad que cubre retrocede. Ver
sdd/site-health-and-error-tracking/design (D4, D5, D7, D8) para el porqué de
cada orden y cada guarda.
"""

import re
from datetime import timedelta
from pathlib import Path

from app import config
from app.database import SessionLocal
from app.models import ErrorEvent, now_utc
from app.services import error_log

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0029_error_events.py"
)


# --- redact() ------------------------------------------------------------


def test_redact_substitutes_a_known_secret_value():
    secret = "un-secreto-de-verdad-largo"
    result = error_log.redact(f"fallo al conectar: {secret}", secrets=[secret])
    assert secret not in result
    assert error_log.REDACTED in result


def test_redact_skips_empty_and_short_secrets():
    # smtp_password ships as "" (config.py), and str.replace("", X) interleaves
    # the replacement between every character — unreadable confetti.
    assert error_log.redact("hola", secrets=["", "abc"]) == "hola"


def test_redact_masks_each_shape_and_keeps_the_field_label():
    bearer = error_log.redact("Authorization: Bearer abcdef123456")
    assert "abcdef123456" not in bearer
    assert error_log.REDACTED in bearer

    sk_style = error_log.redact("connecting with sk-abcdefgh12345678 failed")
    assert "sk-abcdefgh12345678" not in sk_style
    assert error_log.REDACTED in sk_style

    labelled = error_log.redact("api_key=un-valor-secreto-1234")
    assert "un-valor-secreto-1234" not in labelled
    assert "api_key" in labelled  # la etiqueta se conserva
    assert error_log.REDACTED in labelled


def test_query_string_is_always_stripped():
    result = error_log.redact("GET https://api.example.com/x?token=abc123 failed")
    assert "token=abc123" not in result
    assert "https://api.example.com/x?" + error_log.REDACTED in result


def test_redaction_runs_before_truncation(monkeypatch):
    prefix = "ValueError: "
    secret = "abcdefgh12345678"  # 16 chars, ningún carácter de forma conocida
    # Se posiciona para que atraviese el carácter 400 del mensaje compuesto
    # (antes de truncar): si el orden fuera truncar->redactar, sobreviviría
    # un fragmento parcial que no matchea ni el valor ni ninguna forma.
    before = 400 - len(prefix) - (len(secret) // 2)
    message_text = ("a" * before) + secret + ("b" * 200)

    monkeypatch.setattr(error_log, "_live_secrets", lambda: [secret])
    error_log.record_error(source="test", capture_kind="explicit", exc=ValueError(message_text))

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert secret not in row.message
        for start in range(len(secret) - 7):
            assert secret[start : start + 8] not in row.message


# --- record_error() --------------------------------------------------------


def test_record_error_never_raises_when_the_session_cannot_be_opened(monkeypatch):
    def _boom():
        raise RuntimeError("no se pudo abrir la sesion")

    monkeypatch.setattr(error_log, "new_session", _boom)
    assert error_log.record_error(source="test", capture_kind="explicit", exc=ValueError("x")) is None


def test_record_error_does_not_re_enter(monkeypatch):
    calls = {"new_session": 0}

    class FakeSession:
        def add(self, obj):
            pass

        def commit(self):
            # Simula un futuro punto de captura agregado dentro de esta misma
            # rama de fallo: debe ser absorbido por la guarda de reentrancia,
            # no reintentado.
            error_log.record_error(source="test", capture_kind="explicit", exc=ValueError("anidado"))
            raise RuntimeError("commit roto")

        def rollback(self):
            pass

        def close(self):
            pass

    def _fake_new_session():
        calls["new_session"] += 1
        return FakeSession()

    monkeypatch.setattr(error_log, "new_session", _fake_new_session)
    error_log.record_error(source="test", capture_kind="explicit", exc=ValueError("original"))

    assert calls["new_session"] == 1


def test_the_row_is_visible_from_an_independent_session():
    error_log.record_error(source="test", capture_kind="explicit", exc=ValueError("boom"))
    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert row.source == "test"
        assert row.capture_kind == "explicit"
        assert row.exception_type == "ValueError"


def test_the_traceback_comes_from_the_exception_not_ambient_state():
    def _raise_inside_here():
        raise ValueError("boom")

    try:
        _raise_inside_here()
    except ValueError as caught:
        exc = caught

    # Fuera del bloque except: no hay excepción ambiente en curso, igual que
    # dentro de un add_done_callback.
    error_log.record_error(source="test", capture_kind="task_callback", exc=exc)

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert "NoneType: None" not in row.traceback
        assert "_raise_inside_here" in row.traceback


def test_the_traceback_keeps_the_innermost_frames_when_truncated():
    def _recurse(depth: int) -> None:
        if depth == 0:
            raise ValueError("el mas profundo")
        _recurse(depth - 1)

    try:
        _recurse(300)
    except ValueError as caught:
        exc = caught

    error_log.record_error(source="test", capture_kind="explicit", exc=exc)

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert len(row.traceback) <= error_log.TRACEBACK_MAX_LENGTH
        assert "el mas profundo" in row.traceback


# --- purge_error_events() ---------------------------------------------------


def _insert_rows(db, count: int, *, occurred_at):
    for _ in range(count):
        db.add(
            ErrorEvent(
                occurred_at=occurred_at,
                source="test",
                capture_kind="explicit",
                exception_type="ValueError",
                message="m",
            )
        )
    db.commit()


def test_purge_removes_rows_past_the_time_window():
    with SessionLocal() as db:
        _insert_rows(db, 1, occurred_at=now_utc() - timedelta(days=31))
        removed = error_log.purge_error_events(db, days=30, max_rows=0)
        assert removed == 1
        assert db.query(ErrorEvent).count() == 0


def test_purge_enforces_the_row_cap_inside_the_window():
    with SessionLocal() as db:
        # Una ráfaga entera adentro de la ventana de retención: la ventana
        # sola no libera ninguna de estas filas.
        _insert_rows(db, 12, occurred_at=now_utc())
        removed = error_log.purge_error_events(db, days=30, max_rows=5)
        assert removed == 7
        assert db.query(ErrorEvent).count() == 5


def test_purge_treats_zero_as_disabled():
    with SessionLocal() as db:
        _insert_rows(db, 3, occurred_at=now_utc() - timedelta(days=100))
        removed = error_log.purge_error_events(db, days=0, max_rows=0)
        assert removed == 0
        assert db.query(ErrorEvent).count() == 3


# --- Modelo/migración: la misma divergencia que W1 en agent-invitation-email ---


def test_model_indexes_match_the_migration():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    pattern = re.compile(r'op\.create_index\(\s*"([^"]+)",\s*"error_events",\s*\[([^\]]+)\]')
    migration_indexes = {
        (name, tuple(part.strip().strip('"') for part in columns.split(",")))
        for name, columns in pattern.findall(source)
    }

    model_indexes = {
        (index.name, tuple(column.name for column in index.columns))
        for index in ErrorEvent.__table__.indexes
    }

    assert model_indexes == migration_indexes


def test_live_secrets_is_derived_and_not_a_hand_kept_list():
    """A secret setting added later must be redacted from day one.

    The first version listed three fields by hand and had already fallen two
    behind: smtp_password and push_webhook_secret. The latter travels as a
    Bearer header in notifications.py, so it can surface inside an httpx
    exception string. Deriving from the model means the list cannot drift.
    """
    settings = config.get_settings()
    covered = set(error_log._live_secrets())
    for name in ("secret_key", "encryption_key", "whatsapp_bridge_token", "smtp_password", "push_webhook_secret"):
        assert getattr(settings, name) in covered, f"{name} escapes redaction"

    # Integers whose name contains a secret word must not be swept in.
    assert all(isinstance(value, str) for value in covered)


class _FakeStatementError(Exception):
    """Con la forma que SQLAlchemy le da a una StatementError.

    El texto real de IntegrityError/DataError/OperationalError termina con
    "[SQL: ...] [parameters: {...}]", y esos parámetros son la fila que se
    estaba escribiendo. No se importa la clase real para no depender de su
    constructor entre versiones: lo que se prueba es el TEXTO.
    """


def test_sql_bound_parameters_never_reach_a_stored_row():
    """La fuga que la verificación encontró, en su forma exacta.

    Se filtraba por tres eslabones a la vez: el engine adjuntaba los
    parámetros, el patrón de etiqueta no matchea el repr de un dict de Python
    porque la comilla de cierre queda entre la etiqueta y los dos puntos, y el
    truncado por la cola preserva justo el final, que es donde viven. Y las
    capturas HTTP van sin agencia, o sea visibles para todas.
    """
    leaked = (
        "duplicate key value violates unique constraint\n"
        "[SQL: INSERT INTO portal_users (email, password_hash) VALUES (%(email)s, %(password_hash)s)]\n"
        "[parameters: {'email': 'ana@cliente.com', 'password_hash': '$2b$12$abcdefghijklmnop'}]"
    )
    error_log.record_error(source="test", capture_kind="handler", exc=_FakeStatementError(leaked))

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        for stored in (row.message, row.traceback):
            assert "ana@cliente.com" not in stored
            assert "$2b$12$abcdefghijklmnop" not in stored
            assert "parameters:" not in stored


def test_the_engine_itself_does_not_attach_bound_parameters():
    """Segunda capa: la redacción tapa el texto, pero la fuente es el engine.

    hide_parameters=True lo apaga de raíz, y también protege a los logs y a
    cualquier otro consumidor del texto de la excepción, no solo a esta tabla.
    """
    from app.database import engine

    assert engine.hide_parameters is True


def test_a_path_longer_than_its_column_does_not_lose_the_row():
    """El valor lo elige quien llama. Sin recortarlo, el INSERT del propio
    error fallaba y la fila se perdía en silencio — justo el caso que este
    registro existe para no dejar pasar."""
    error_log.record_error(
        source="test",
        capture_kind="handler",
        exc=ValueError("x"),
        request_path="/" + ("a" * 500),
        request_method="GET" + ("!" * 40),
        subject_ref="s" * 400,
    )

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert len(row.request_path) == error_log.REQUEST_PATH_MAX_LENGTH
        assert len(row.request_method) == error_log.REQUEST_METHOD_MAX_LENGTH
        assert len(row.subject_ref) == error_log.SUBJECT_REF_MAX_LENGTH


def test_the_traceback_column_is_redacted_too_and_not_only_the_message(monkeypatch):
    """El escenario del spec dice "toda columna guardada, incluida traceback".
    Lo que había afirmaba solo `message`."""
    secret = "un-secreto-largo-de-verdad"
    monkeypatch.setattr(error_log, "_live_secrets", lambda: [secret])

    def _raise_with_the_secret():
        raise ValueError(f"fallo con {secret} adentro")

    try:
        _raise_with_the_secret()
    except ValueError as exc:
        error_log.record_error(source="test", capture_kind="explicit", exc=exc)

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert secret not in row.traceback
        assert secret not in row.message
        # Y sigue sirviendo para lo que existe: el frame que rompió está.
        assert "_raise_with_the_secret" in row.traceback


def test_a_long_traceback_keeps_its_innermost_frames(monkeypatch):
    """El test anterior recursaba 300 veces sobre una línea, y
    StackSummary.format colapsa los frames repetidos ("[Previous line repeated
    N more times]"), así que el stack quedaba muy por debajo del límite y el
    truncado no se ejercitaba nunca. Acá el largo se fuerza de verdad."""
    padding = "x" * (error_log.TRACEBACK_MAX_LENGTH * 2)

    def _the_innermost_frame():
        raise ValueError(padding)

    try:
        _the_innermost_frame()
    except ValueError as exc:
        error_log.record_error(source="test", capture_kind="explicit", exc=exc)

    with SessionLocal() as db:
        row = db.query(ErrorEvent).one()
        assert len(row.traceback) == error_log.TRACEBACK_MAX_LENGTH
        # Truncado por la cola: lo que sobrevive es el final, que es donde
        # está la respuesta a "dónde rompió". Se busca la subcadena y no un
        # endswith: format_exception cierra con un salto de línea.
        assert padding[-50:] in row.traceback

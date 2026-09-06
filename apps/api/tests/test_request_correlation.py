"""Un identificador por pedido, en cada línea que ese pedido produce.

Lo que se prueba no es que el identificador exista, sino las tres cosas que lo
harían inútil o peligroso: que no llegue a los logs, que se repita entre
pedidos, y que quien llama pueda elegir qué se escribe en el archivo de logs.
"""

import contextvars
import logging

from fastapi.testclient import TestClient

from app.logging_setup import (
    JsonFormatter,
    RequestIdFilter,
    current_request_id,
    set_request_id,
)

HEADER = "x-request-id"


class TestTheIncomingHeaderIsNotTrusted:
    """Un valor que llega por cabecera y termina en un log es una entrada que
    elige quien llama. Sin validar la forma, ahí se meten saltos de línea y se
    fabrican entradas enteras que nunca ocurrieron."""

    def test_a_well_formed_id_is_honoured(self, client: TestClient):
        """Una traza que empezó en otro servicio no se corta acá."""
        response = client.get("/api/auth/status", headers={HEADER: "abc-123_XYZ.9"})
        assert response.headers[HEADER] == "abc-123_XYZ.9"

    def test_a_newline_is_refused(self, client: TestClient):
        assert set_request_id("uno\nINFO fabricado") != "uno\nINFO fabricado"
        assert "\n" not in current_request_id()

    def test_other_shapes_are_refused(self):
        for hostile in ("con espacio", "a" * 65, "punto;coma", "", "   ", None, "\r\nX"):
            resolved = set_request_id(hostile)
            assert resolved != hostile
            assert resolved.isalnum(), resolved

    def test_a_refused_one_still_gets_an_id(self, client: TestClient):
        """Rechazar el valor no puede dejar al pedido sin identificador."""
        response = client.get("/api/auth/status", headers={HEADER: "no vale"})
        assert response.headers[HEADER]
        assert response.headers[HEADER] != "no vale"


def test_every_response_carries_one(client: TestClient):
    """La cabecera de vuelta es el punto: quien reporta un problema la cita."""
    assert client.get("/api/auth/status").headers[HEADER]


def test_two_requests_do_not_share_one(client: TestClient):
    first = client.get("/api/auth/status").headers[HEADER]
    second = client.get("/api/auth/status").headers[HEADER]
    assert first != second


def test_a_failed_request_still_answers_with_one(client: TestClient):
    """Justamente el caso en que alguien va a querer el identificador."""
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me").headers[HEADER]


class TestTheLogLinesCarryIt:
    def _record(self) -> logging.LogRecord:
        record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "algo paso", None, None)
        RequestIdFilter().filter(record)
        return record

    def test_the_filter_puts_it_on_the_record(self):
        set_request_id("trazable-1")
        assert self._record().request_id == "trazable-1"

    def test_outside_a_request_it_is_a_dash(self):
        """Un barrido en segundo plano sigue logueando; solo que sin identificador.

        Se corre en un contexto nuevo y vacio, que es exactamente lo que es
        estar fuera de un pedido. Llamar a ``set_request_id("")`` no serviria:
        genera uno, y hace bien, porque un pedido siempre tiene identificador.
        """
        set_request_id("dentro-de-un-pedido")
        record = contextvars.Context().run(self._record)
        assert record.request_id == "-"
        assert current_request_id() == "dentro-de-un-pedido"

    def test_json_carries_it(self):
        set_request_id("trazable-2")
        line = JsonFormatter().format(self._record())
        assert '"request_id": "trazable-2"' in line
        assert '"message": "algo paso"' in line

    def test_a_record_from_a_library_does_not_break_the_format(self):
        """Es un filtro y no un formateador por esto: un formateador que
        referencia un campo inexistente lanza, y los registros que emite una
        librería de terceros nunca lo traen."""
        foreign = logging.LogRecord("httpx", logging.WARNING, __file__, 1, "algo externo", None, None)
        assert not hasattr(foreign, "request_id")
        assert '"request_id": "-"' in JsonFormatter().format(foreign)

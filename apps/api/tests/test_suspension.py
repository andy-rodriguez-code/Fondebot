"""Suspender una empresa le corta el servicio, sin tocarle un dato.

`Client.is_active` existía desde el principio y no cortaba nada: el único
lugar que lo leía era el contador del panel. Una empresa que dejaba de pagar
seguía atendiendo por WhatsApp toda la noche.

Lo que se prueba acá es que el corte alcance los cuatro caminos por los que
entra una petición de afuera —portal, widget, WhatsApp y mobile—, que no se
borre nada, y que el corte sea para la empresa y no para quien la administra.
"""

from fastapi.testclient import TestClient

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


import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet

from .config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": user_id, "exp": expires}, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def create_portal_token(client_id: str, portal_slug: str, portal_user_id: str | None = None) -> str:
    """Sesión para el portal de un cliente.

    ``sub`` sigue siendo el cliente, así los tokens emitidos antes de que
    existieran las personas del portal se siguen resolviendo. ``pu`` nombra a la
    persona cuando hay una, y eso es lo que permite atribuir una respuesta y
    atar un dispositivo a alguien en vez de a todo el negocio.
    """
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    payload: dict = {"sub": client_id, "portal_slug": portal_slug, "type": "portal", "exp": expires}
    if portal_user_id:
        payload["pu"] = portal_user_id
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_portal_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        if payload.get("type") != "portal":
            return None
        return payload
    except jwt.PyJWTError:
        return None


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:3]}••••••••{value[-4:]}"


def generate_invitation_token() -> str:
    """Un token de invitación de un solo uso, 256 bits de entropía.

    A diferencia de una contraseña humana, esto no es un secreto de baja
    entropía: no hace falta (ni conviene) el costo de bcrypt para protegerlo,
    ver D1 en el diseño de agent-invitation-email. ``token_urlsafe(32)``
    devuelve 43 caracteres base64 URL-safe.
    """
    return secrets.token_urlsafe(32)


def hash_invitation_token(raw_token: str) -> str:
    """Digest determinístico para buscar por índice único (D1/D2).

    Un hash determinístico permite ``SELECT ... WHERE token_hash = :digest``
    en un índice único en vez de recorrer cada fila pendiente con un hash con
    sal. No hace falta resistencia contra diccionario: el valor de entrada es
    un token de 256 bits generado por el propio servidor, no algo que alguien
    eligió.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


def verify_invitation_token(raw_token: str, token_hash: str) -> bool:
    """Comparación en tiempo constante después de la búsqueda por índice.

    Esto es defensa en profundidad y consistencia con el resto del código
    (``whatsapp.py``, ``whatsapp_cloud_webhook.py``), no lo que hace segura la
    verificación: eso ya lo garantiza el hash (D2). El atacante controla el
    valor sin hashear, no el digest, así que no hay un byte a byte que recorrer
    contra el hash guardado.
    """
    return hmac.compare_digest(hash_invitation_token(raw_token), token_hash)

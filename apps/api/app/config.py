from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


APP_DIR = Path(__file__).resolve().parents[1]   # apps/api
REPO_ROOT = Path(__file__).resolve().parents[3]  # raíz del monorepo (para un .env local compartido)


# Valores de relleno que están publicados en este repositorio: el default del
# propio código, el de .env.example y el de .env.docker.example. Arrancar con
# cualquiera de ellos equivale a no tener secreto, así que get_settings() se
# niega a devolver una configuración que los siga usando. El primer elemento de
# cada tupla es además el default del campo.
INSECURE_VALUES: dict[str, tuple[str, ...]] = {
    "secret_key": (
        "dev-local-change-this-key-please",
        "change-this-long-random-key-in-production",
        "CHANGE_THIS_SESSION_SECRET",
    ),
    "encryption_key": (
        "dev-local-change-this-key-too",
        "change-this-other-long-random-key",
        "CHANGE_THIS_ENCRYPTION_KEY",
    ),
    "whatsapp_bridge_token": (
        "dev-local-change-this-bridge-token",
        "generate-a-long-random-token-for-the-bridge",
        "CHANGE_THIS_INTERNAL_TOKEN",
    ),
}


class Settings(BaseSettings):
    app_name: str = "OpenLivery API"
    database_url: str = "postgresql+psycopg://openlivery:openlivery@localhost:5432/openlivery"
    secret_key: str = INSECURE_VALUES["secret_key"][0]
    encryption_key: str = INSECURE_VALUES["encryption_key"][0]
    # La URL publica del deployment: con la que alguien de afuera llega a la
    # app. No es solo CORS, aunque el nombre lo sugiera. Se usa para armar dos
    # enlaces que tienen que funcionar desde otra maquina:
    #   - el de aceptar una invitacion (routers/departments.py)
    #   - el del webhook que se pega en el panel de Meta (routers/whatsapp_cloud.py)
    # Dejarla en el valor por defecto no falla en ningun lado: simplemente
    # genera enlaces a localhost que solo sirven en el servidor. Y si cambias
    # WEB_PORT, esta tiene que cambiar con el.
    #
    # No se deduce del pedido entrante a proposito: quien manda el header Host
    # es quien llama, asi que un enlace armado con el se puede envenenar para
    # que apunte a otro sitio llevando un token valido.
    frontend_url: str = "http://localhost:3000"
    access_token_minutes: int = 60 * 24 * 7
    # Flags de la cookie de sesión. Los valores por defecto sirven para HTTP
    # local; en producción detrás de HTTPS poné cookie_secure=true (y
    # cookie_samesite=none cuando el frontend y la API están en sitios
    # distintos).
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    # Límite de tasa en endpoints públicos/sin autenticar (por IP del cliente).
    # Desactivalo solo para tests, o cuando un proxy adelante ya aplica límites.
    rate_limit_enabled: bool = True
    # Proxies de confianza para leer la IP real del cliente. Solo se hace caso a
    # ``X-Forwarded-For`` cuando la conexión viene de una de estas direcciones;
    # de lo contrario se usa la IP del peer, porque un header que manda quien
    # llama no sirve para limitar tráfico. Acepta IPs sueltas y rangos CIDR
    # separados por coma. Los valores por defecto cubren loopback y las redes
    # privadas donde vive el gateway de Docker. Dejalo vacío para no confiar
    # nunca en el header.
    trusted_proxies: str = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
    # Una instancia autoalojada es de una sola agencia por defecto: el primer
    # registro crea la agencia dueña y cierra el alta pública (como el setup de
    # owner de n8n). Activalo solo cuando un mismo deployment tiene que alojar
    # muchas agencias.
    allow_multi_agency: bool = False
    # Protección SSRF para las tools HTTP de los agentes: se rechazan las URLs
    # que resuelven a direcciones privadas o de loopback. Activalo solo en
    # deployments autoalojados donde las tools necesitan llegar a servicios
    # internos.
    tools_allow_private_urls: bool = False
    storage_dir: Path = APP_DIR / "storage"
    backend_url: str = "http://localhost:8000"
    whatsapp_bridge_url: str = "http://localhost:3101"
    whatsapp_bridge_token: str = "dev-local-change-this-bridge-token"
    # Raíz de la Graph API de Meta que usa el canal de WhatsApp Cloud API;
    # sobreescribila para apuntar a un servidor mock en los tests.
    meta_graph_base_url: str = "https://graph.facebook.com/v23.0"
    # Ventana de silencio antes de que la IA responda un mensaje de WhatsApp:
    # mientras siguen llegando mensajes del visitante el temporizador se
    # reinicia, y toda la ráfaga se contesta con una sola respuesta. Con 0 se
    # vuelve al flujo inmediato de una respuesta por mensaje.
    reply_debounce_seconds: float = 8.0
    # Las conversaciones que atiende la IA se resuelven solas después de esta
    # cantidad de horas sin mensajes de ninguna de las dos partes. Las
    # conversaciones que tomó una persona nunca se cierran automáticamente: eso
    # lo decide únicamente esa persona. Con 0 se desactiva.
    auto_resolve_after_hours: float = 24.0

    # Notificaciones push para la app mobile. "none" (el valor por defecto) no
    # manda nada y no requiere cuenta con nadie; "webhook" hace POST de cada
    # evento a push_webhook_url, así lo enrutás por donde ya tengas armado. Un
    # deployment puede registrar más proveedores al arrancar: mirá
    # app/services/notifications.py y docs/push-notifications.md.
    push_provider: str = "none"
    push_webhook_url: str = ""
    push_webhook_secret: str = ""

    # Envío de invitaciones al portal por mail. "none" (el default) no manda
    # nada: la invitación se crea igual y el link queda en la respuesta de la
    # API para que la persona admin lo reenvíe a mano. "smtp" manda el mail de
    # verdad contra un servidor SMTP operado por quien despliega. Ver
    # app/services/emails.py — smtp_password legítimamente queda vacío en toda
    # instalación que no usa mail, así que a propósito NO entra en
    # INSECURE_VALUES: ese guard es para valores de relleno publicados, no para
    # un campo opcional que la mayoría de instalaciones deja sin usar.
    email_provider: str = "none"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    # Minutos de vigencia de un token de invitación (24 h por defecto).
    invitation_token_minutes: int = 1440

    # Retención del registro nativo de errores (app/services/error_log.py):
    # una fila más vieja que estos días, o más allá de este tope de filas
    # (lo que se cumpla primero), se purga en el barrido en segundo plano.
    # Ninguno de los dos límites solo alcanza: una ráfaga cabe entera dentro
    # de la ventana de tiempo, y una instancia tranquila nunca llega al tope
    # de filas. 0 desactiva ese límite en particular.
    error_log_retention_days: int = 30
    error_log_max_rows: int = 5000

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", APP_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    unchanged = [name for name, values in INSECURE_VALUES.items() if getattr(settings, name) in values]
    if unchanged:
        raise RuntimeError(
            "Estos secretos siguen con un valor de relleno que está publicado en el "
            f"repositorio: {', '.join(name.upper() for name in unchanged)}. Quien lo conozca "
            "puede firmar sesiones ajenas y descifrar las credenciales guardadas. Generá "
            "valores propios antes de arrancar: ./scripts/generate-docker-env.sh para "
            "Docker, o copiá .env.example a .env y reemplazá esas claves "
            "(por ejemplo con `openssl rand -hex 32`)."
        )
    return settings

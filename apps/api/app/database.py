from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


# Un NAT o un pooler entre la app y un Postgres remoto puede cortar conexiones
# TCP ociosas en silencio (sin RST); un socket muerto del pool después se cuelga
# incluso en el SELECT 1 de pool_pre_ping, hasta que vence el timeout de
# retransmisión del kernel. Los keepalives destapan el corte en ~60s y
# pool_recycle retira las conexiones antes de que puedan quedar rancias.
KEEPALIVE_CONNECT_ARGS = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "connect_timeout": 10,
}

engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    pool_recycle=240,
    connect_args=KEEPALIVE_CONNECT_ARGS,
    # Sin esto, SQLAlchemy le pega "[SQL: ...] [parameters: {...}]" al texto de
    # CUALQUIER StatementError — IntegrityError, DataError, OperationalError —,
    # y esos parámetros son la fila que se estaba escribiendo: mails, teléfonos,
    # password_hash, token_hash, ciphertext. Cualquier capa que guarde o loguee
    # el texto de la excepción guarda también esos datos.
    hide_parameters=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def new_session():
    """Abre una sesión. El único lugar donde se crea una sesión.

    Los handlers de request reciben una a través de ``get_db``, que FastAPI
    permite sustituir en un deployment; la suite de tests hace exactamente eso.
    El trabajo que corre fuera de un request no tiene dependencia que recibir,
    así que llama a esta función en vez de ir directo a ``SessionLocal``.

    Que ambos caminos pasen por acá es justamente el punto: una sesión
    sustituida llega a todas las queries, no solo a las ruteadas. Llamar a
    ``SessionLocal()`` desde otro lado deja ese código afuera en silencio, y la
    falla resultante aparece dentro de la tarea en segundo plano que hizo la
    llamada, en vez de en una respuesta.
    """
    return SessionLocal()


def get_db():
    db = new_session()
    try:
        yield db
    finally:
        db.close()

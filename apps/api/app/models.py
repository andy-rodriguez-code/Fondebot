import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def new_public_id() -> str:
    return uuid.uuid4().hex


def new_domain_token() -> str:
    return uuid.uuid4().hex


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Agency(Base):
    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(180))
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    brand_color: Mapped[str] = mapped_column(String(20), default="#075985")
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    users: Mapped[list["User"]] = relationship(back_populates="agency", cascade="all, delete-orphan")

    @property
    def logo_url(self) -> str | None:
        return f"/api/agency/logo?v={int(self.created_at.timestamp())}" if self.logo_data else None


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(320), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    agency: Mapped[Agency] = relationship(back_populates="users")


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    industry: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    general_context: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Logo opcional por cliente, que se muestra en el widget y en el portal (si
    # no hay, cae al logo de la agencia). Los bytes se guardan en Postgres, igual
    # que el logo de la agencia.
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    logo_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    portal_slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    portal_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    portal_title: Mapped[str] = mapped_column(String(180), default="")
    # Dominio propio opcional para el portal de este cliente. Se verifica con un
    # desafío TXT de DNS; solo los dominios verificados se rutean y reciben un
    # certificado on-demand.
    portal_domain: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    portal_domain_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    portal_domain_token: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    agents: Mapped[list["Agent"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    whatsapp_channel: Mapped["WhatsAppChannel | None"] = relationship(
        back_populates="client", cascade="all, delete-orphan", uselist=False
    )
    whatsapp_cloud_channel: Mapped["WhatsAppCloudChannel | None"] = relationship(
        back_populates="client", cascade="all, delete-orphan", uselist=False
    )
    portal_users: Mapped[list["PortalUser"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    departments: Mapped[list["Department"]] = relationship(
        back_populates="client", cascade="all, delete-orphan", order_by="Department.position, Department.name"
    )

    @property
    def logo_url(self) -> str | None:
        return f"/api/clients/{self.id}/logo?v={int(self.updated_at.timestamp())}" if self.logo_mime else None


class Department(Base):
    """Una dependencia del negocio del cliente: tesorería, contabilidad, recaudo.

    Es la puerta de entrada de WhatsApp. Al abrirse una conversación se le
    ofrece al contacto el menú de dependencias; la que elige se queda con el
    caso y lo contesta con su propio agente. Las personas del portal pertenecen
    a una sola y solo ven lo suyo, así que la dependencia no es una etiqueta:
    es la frontera de visibilidad dentro de un mismo cliente.

    Una por cliente lleva ``is_entry``: la de recepción, que atiende mientras el
    contacto todavía no eligió, y a la que caen las conversaciones cuando no
    hay coincidencia.
    """

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("client_id", "slug", name="uq_departments_client_slug"),
        # Una sola recepción por cliente, garantizado por la base y no por el
        # router: dos entradas dejarían el ruteo por defecto a merced del orden.
        Index("uq_departments_client_entry", "client_id", unique=True, postgresql_where=text("is_entry")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    # El agente que contesta lo de esta dependencia. Tiene que ser del mismo
    # cliente; eso lo valida el router.
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # Identificador estable que viaja como payload del botón, así renombrar la
    # dependencia no rompe los menús que ya se mandaron.
    slug: Mapped[str] = mapped_column(String(60))
    # Línea de apoyo que solo se ve en el menú de lista de la Cloud API; los
    # botones no tienen descripción.
    description: Mapped[str] = mapped_column(String(72), default="")
    is_entry: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Orden en el menú. El número que responde el contacto en Baileys sale de
    # esta posición, así que reordenar cambia lo que significa "2".
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    client: Mapped["Client"] = relationship(back_populates="departments")
    agent: Mapped["Agent"] = relationship()


class ProviderCredential(Base):
    """Una API key de proveedor de IA por agencia (traé tu propia clave).
    ``provider`` es "openai" o "anthropic"; la URL base se resuelve a partir del
    proveedor."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("agency_id", "provider", name="uq_provider_credentials_agency_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    # Brief estructurado del negocio. Campos guiados y opcionales que se componen
    # dentro del prompt de sistema, junto con las instrucciones de texto libre.
    brief_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief_products: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief_audience: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief_policies: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief_goal: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief_dos: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief_donts: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Proveedor de IA ("openai" o "anthropic"); se usa la clave de la agencia para ese proveedor.
    provider: Mapped[str] = mapped_column(String(30), default="openai", server_default="openai")
    model: Mapped[str] = mapped_column(String(180), default="")
    # Zona horaria IANA (por ejemplo "America/Bogota"); se inyecta en el prompt de
    # sistema para que el agente sepa la fecha y hora local. "UTC" si no se define.
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    manual_context: Mapped[str] = mapped_column(Text, default="")
    # Ajustes de generación. El servicio de IA aplica los parámetros de sampling
    # con la mejor intención posible (los modelos que los rechazan caen a sus
    # valores por defecto).
    temperature: Mapped[float] = mapped_column(Float, default=0.7, server_default="0.7")
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, server_default="2048")
    # Cuántos mensajes anteriores se conservan como memoria de la conversación.
    memory_limit: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    # Capacidades multimodales. Cuando están activadas, las imágenes entrantes las
    # describe un modelo de visión y el audio entrante se transcribe antes de
    # llegar al agente.
    image_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    image_model: Mapped[str] = mapped_column(String(180), default="", server_default="")
    audio_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    audio_model: Mapped[str] = mapped_column(String(180), default="whisper-1", server_default="whisper-1")
    # Widget de chat web embebible.
    widget_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    widget_public_id: Mapped[str] = mapped_column(String(64), default=new_public_id, unique=True, index=True)
    widget_greeting: Mapped[str] = mapped_column(Text, default="", server_default="")
    widget_color: Mapped[str] = mapped_column(String(20), default="", server_default="")
    widget_position: Mapped[str] = mapped_column(String(10), default="right", server_default="right")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    client: Mapped[Client] = relationship(back_populates="agents")
    documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    qa_pairs: Mapped[list["AgentQA"]] = relationship(back_populates="agent", cascade="all, delete-orphan", order_by="AgentQA.position")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    whatsapp_channels: Mapped[list["WhatsAppChannel"]] = relationship(back_populates="agent")
    whatsapp_cloud_channels: Mapped[list["WhatsAppCloudChannel"]] = relationship(back_populates="agent")
    tools: Mapped[list["AgentTool"]] = relationship(back_populates="agent", cascade="all, delete-orphan", order_by="AgentTool.created_at")


class AgentTool(Base):
    """Una tool propia que el agente puede llamar: un endpoint HTTP definido por
    la persona usuaria ("http") o un servidor MCP externo ("mcp")."""

    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "name", name="uq_agent_tools_agent_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Endpoint HTTP (puede tener marcadores {param} en la ruta) o URL del servidor MCP.
    url: Mapped[str] = mapped_column(Text, default="")
    # Solo para tools HTTP.
    http_method: Mapped[str] = mapped_column(String(10), default="GET")
    prompt_instructions: Mapped[str] = mapped_column(Text, default="")
    body_params: Mapped[list] = mapped_column(JSON, default=list)
    query_params: Mapped[list] = mapped_column(JSON, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    # Solo para servidores MCP. cached_tools guarda el último resultado de
    # list_tools, así los pedidos de chat nunca se bloquean esperando el
    # descubrimiento; se refresca al guardar o al probar la conexión.
    transport: Mapped[str] = mapped_column(String(20), default="streamable_http")
    cached_tools: Mapped[list] = mapped_column(JSON, default=list)
    tools_cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # El diccionario completo de headers de autenticación, cifrado en reposo;
    # la API nunca lo devuelve.
    encrypted_headers: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    agent: Mapped[Agent] = relationship(back_populates="tools")


class WhatsAppChannel(Base):
    __tablename__ = "whatsapp_channels"
    __table_args__ = (UniqueConstraint("client_id", name="uq_whatsapp_channels_client_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    phone_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    encrypted_auth_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_qr: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    client: Mapped[Client] = relationship(back_populates="whatsapp_channel")
    agent: Mapped[Agent] = relationship(back_populates="whatsapp_channels")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="whatsapp_channel")


class WhatsAppCloudChannel(Base):
    """Canal oficial de WhatsApp Business Cloud API (Graph API de Meta). Convive
    con el canal de Baileys: un cliente puede tener uno de cada uno, en números
    distintos. Las credenciales se cargan a mano (traé tu propia app de Meta)."""

    __tablename__ = "whatsapp_cloud_channels"
    __table_args__ = (UniqueConstraint("client_id", name="uq_whatsapp_cloud_channels_client_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    phone_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    phone_number_id: Mapped[str] = mapped_column(String(80), default="", server_default="")
    waba_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_app_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Token que la persona dueña pega en la configuración del webhook de su app
    # de Meta; tiene que poder volver a mostrarse, así que se guarda en texto
    # plano, igual que portal_domain_token.
    webhook_verify_token: Mapped[str] = mapped_column(String(64), default=new_public_id, server_default="")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    client: Mapped[Client] = relationship(back_populates="whatsapp_cloud_channel")
    agent: Mapped[Agent] = relationship(back_populates="whatsapp_cloud_channels")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="whatsapp_cloud_channel")


class AgentQA(Base):
    __tablename__ = "agent_qa"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    agent: Mapped[Agent] = relationship(back_populates="qa_pairs")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_data: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="processed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    agent: Mapped[Agent] = relationship(back_populates="documents")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    # Vector de embedding guardado como array JSON de floats (portable a
    # cualquier Postgres; la similitud se calcula en Python). Cambiar a pgvector
    # cuando haya escala.
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(180))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, index=True)


class Contact(Base):
    """Una persona con la que habla el negocio, una por cliente y número.

    Se crea la primera vez que escribe un número, o a mano desde el portal. Un
    contacto puede tener muchas conversaciones a lo largo del tiempo, una por
    caso.
    """

    __tablename__ = "contacts"
    __table_args__ = (
        Index("uq_contacts_client_phone", "client_id", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180), default="")
    # Solo dígitos, tal como lo reporta WhatsApp. None para gente sin número.
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="contact", passive_deletes=True)


class Conversation(Base):
    """Un caso con un contacto: se abre con su primer mensaje y termina cuando
    se resuelve. El siguiente mensaje después de eso abre una conversación
    nueva, así que un mismo id de chat puede aparecer acá muchas veces."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_whatsapp_chat", "whatsapp_channel_id", "external_chat_id"),
        Index("ix_conversations_whatsapp_cloud_chat", "whatsapp_cloud_channel_id", "external_chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240), default="New conversation")
    mode: Mapped[str] = mapped_column(String(30), default="ai")
    channel: Mapped[str] = mapped_column(String(40), default="playground")
    whatsapp_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), nullable=True, index=True
    )
    whatsapp_cloud_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("whatsapp_cloud_channels.id", ondelete="CASCADE"), nullable=True, index=True
    )
    external_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # La dependencia dueña del caso. None en los clientes que no usan
    # dependencias, y en todo lo anterior a la migración 0027.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Cuándo se le ofreció el menú de dependencias al contacto. Existe para no
    # repetirlo en cada mensaje: el menú se manda una sola vez por conversación.
    menu_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # En qué estado está el caso, independientemente de quién responda
    # (``mode``): open | resolved. Si un contacto escribe a una conversación
    # resuelta, la reabre.
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Primera respuesta de cualquier tipo (IA o persona) desde que se abrió la conversación.
    first_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuándo fue la última vez que una persona le sacó la conversación a la IA.
    taken_over_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # La persona del portal que está atendiendo esta conversación, cuando hay
    # una. Se limpia cuando vuelve a la IA, o cuando se libera para que la tome
    # otra persona.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Lo pone un mensaje entrante y lo limpia la siguiente respuesta: cuánto
    # hace que el contacto está esperando que le contesten.
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    agent: Mapped[Agent] = relationship(back_populates="conversations")
    contact: Mapped[Contact | None] = relationship(back_populates="conversations")
    department: Mapped["Department | None"] = relationship()
    assignee: Mapped["PortalUser | None"] = relationship(foreign_keys=[assignee_id])
    whatsapp_channel: Mapped[WhatsAppChannel | None] = relationship(back_populates="conversations")
    whatsapp_cloud_channel: Mapped[WhatsAppCloudChannel | None] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "external_message_id", name="uq_messages_conversation_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    # message: intercambiado con el contacto. activity: algo que le pasó a la
    # conversación (se resolvió, se reabrió, la tomó alguien), que se muestra en
    # el hilo pero nunca se envía ni se le pasa al modelo. Ver ``activity``.
    kind: Mapped[str] = mapped_column(String(20), default="message", server_default="message")
    # Para kind=activity: {"event": "resolved" | "reopened" | "reopened_by_contact"
    # | "taken_over" | "returned_to_ai"}. ``sender_name`` lleva quién lo hizo, y
    # ``content`` una frase para los clientes que no conocen el evento.
    activity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    # Lo que ve el LLM para este mensaje cuando difiere del contenido mostrado
    # (por ejemplo, la descripción de una imagen o la transcripción de un audio,
    # para un mensaje de media cuyo contenido visible es solo el epígrafe).
    llm_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    # Uso de tools detrás de una respuesta del asistente: [{name, arguments, result_preview, is_error}].
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sender_type: Mapped[str] = mapped_column(String(30), default="visitor")
    sender_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    # La persona del portal que escribió una respuesta humana, cuando se sabe.
    # sender_name queda como el texto que se muestra; este es el vínculo del que
    # dependen los reportes.
    portal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True
    )
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Para mensajes salientes por la WhatsApp Cloud API: sent | delivered |
    # read | failed, tal como lo reportan los acuses de Meta. None hasta el primero.
    delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # La reacción con emoji del negocio a este mensaje (del visitante), espejada
    # en el portal para que quien opera vea el mismo gesto que vio la persona
    # del otro lado en WhatsApp.
    reaction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Se define cuando esta respuesta cita un mensaje anterior puntual (responder deslizando).
    quoted_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageAttachment.created_at"
    )


class MessageAttachment(Base):
    """El archivo de media original detrás de un mensaje de chat (imagen, nota de
    voz, documento).

    Los bytes viven en Postgres, igual que KnowledgeDocument/Agency.logo_data; el
    LLM nunca lee esta tabla: recibe el texto ya resuelto en Message.llm_content.
    """

    __tablename__ = "message_attachments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # image | audio | file
    mime: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    message: Mapped[Message] = relationship(back_populates="attachments")

class PortalUser(Base):
    """Una persona del negocio del cliente que puede responder desde el portal.

    Antes de esta tabla, un portal tenía un solo mail y contraseña compartidos
    por todo el negocio. Eso funciona en un navegador y se cae con push: no
    podés saber a qué teléfono notificar, quién respondió, ni revocarle el acceso
    a una sola persona. Desde la 0021 este es el único login del portal; la
    migración trajo todas las credenciales viejas, así que a nadie se le dejó de
    funcionar la contraseña.
    """

    __tablename__ = "portal_users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    email: Mapped[str] = mapped_column(String(320), index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # La dependencia a la que pertenece. None significa que ve todo el cliente:
    # es lo que queda para quien supervisa, y para todas las cuentas que ya
    # existían antes de que hubiera dependencias.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    client: Mapped["Client"] = relationship(back_populates="portal_users")
    department: Mapped["Department | None"] = relationship()
    devices: Mapped[list["PushDevice"]] = relationship(back_populates="portal_user", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("client_id", "email", name="uq_portal_users_client_email"),)


class PortalInvitation(Base):
    """Una invitación pendiente a alguien que todavía no tiene ``PortalUser``.

    ``token_hash`` es el único rastro del token en la base: el valor sin
    hashear vive solo en memoria, en el cuerpo del mail o en la respuesta de
    creación cuando no hay proveedor configurado (ver services/emails.py e
    services/invitations.py). ``accepted_at`` no nulo la vuelve inservible para
    siempre; ``expires_at`` la vence a las 24 h independientemente del uso.

    ``department_id`` usa CASCADE, no SET NULL como ``PortalUser.department_id``:
    para una invitación *pendiente*, quedarse sin dependencia no es "ve todo el
    cliente", es una promoción de privilegios que nadie pidió. Ver el
    docstring de la migración 0028 para el detalle completo.
    """

    __tablename__ = "portal_invitations"
    # Espejo de los índices de la migración 0028. Sin esto, la suite —que arma
    # el esquema con ``Base.metadata.create_all``— corre contra una tabla sin
    # ninguna de las dos garantías, y un defecto que la base rechazaría en
    # producción pasa en verde. Las dos son estructurales, no convenciones:
    # el hash es único, y solo puede existir una invitación PENDIENTE por
    # cliente y dirección (las aceptadas quedan como rastro y se excluyen).
    __table_args__ = (
        Index("uq_portal_invitations_token_hash", "token_hash", unique=True),
        Index(
            "uq_portal_invitations_client_email_pending",
            "client_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    # server_default además del default de Python, igual que en la migración
    # 0028: sin él, un INSERT que no pase por el ORM deja la columna en NULL.
    name: Mapped[str] = mapped_column(String(160), default="", server_default="")
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    client: Mapped["Client"] = relationship()
    department: Mapped["Department | None"] = relationship()


class PushDevice(Base):
    """Un teléfono que pidió que le avisen cuando una conversación necesita una
    persona.

    El registro es agnóstico del proveedor a propósito: ``token`` es lo que sea
    que el proveedor de notificaciones configurado necesite para llegar a esta
    instalación (un token de dispositivo, un id de suscripción, un tópico), y
    ``provider`` deja registrado cuál lo emitió, así un servidor que cambia de
    proveedor ignora las filas viejas en vez de mandarlas a un lugar sin sentido.

    El token es único, así que volver a registrar la misma instalación actualiza
    la fila en vez de acumular duplicados. Las filas mueren junto con su persona
    usuaria o su cliente.
    """

    __tablename__ = "push_devices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_uuid)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    portal_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    token: Mapped[str] = mapped_column(String(400), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="")
    platform: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    portal_user: Mapped["PortalUser | None"] = relationship(back_populates="devices")

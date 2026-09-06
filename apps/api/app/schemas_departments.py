import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .schemas import InvitationOut


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    agent_id: uuid.UUID
    description: str = Field(default="", max_length=72)
    is_entry: bool = False
    enabled: bool = True
    position: int = Field(default=0, ge=0, le=999)
    # Invitación opcional a quien va a atender esta dependencia. Ausente
    # (default None) deja la creación de la dependencia exactamente como
    # antes (Spec: Optional Invitation On Department Creation).
    invite_email: EmailStr | None = None
    invite_name: str = Field(default="", max_length=160)

    @field_validator("name", "description", "invite_name")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    agent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=72)
    is_entry: bool | None = None
    enabled: bool | None = None
    position: int | None = Field(default=None, ge=0, le=999)

    @field_validator("name", "description")
    @classmethod
    def _trim(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    slug: str
    description: str
    is_entry: bool
    enabled: bool
    position: int
    # Nombre del agente que contesta, para no obligar a la interfaz a cruzar
    # este listado con el de agentes.
    agent_name: str | None = None
    # La invitación pendiente de esta dependencia, si tiene una. None cuando
    # nunca se invitó a nadie, o cuando la última invitación ya fue aceptada.
    invitation: InvitationOut | None = None

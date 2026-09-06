from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, Client, Conversation, Department, Message, UsageRecord, User, WhatsAppChannel, now_utc
from ..schemas import DashboardMetrics, DashboardOut
from ..services.conversation_state import exchanged_only


router = APIRouter(prefix="/dashboard", tags=["Inicio"])


@router.get("", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    agency_id = user.agency_id
    clients = db.scalar(select(func.count(Client.id)).where(Client.agency_id == agency_id)) or 0
    active_clients = db.scalar(
        select(func.count(Client.id)).where(Client.agency_id == agency_id, Client.is_active.is_(True))
    ) or 0
    agents = db.scalar(select(func.count(Agent.id)).where(Agent.agency_id == agency_id)) or 0
    active_agents = db.scalar(
        select(func.count(Agent.id)).where(Agent.agency_id == agency_id, Agent.is_active.is_(True))
    ) or 0
    conversations = db.scalar(
        select(func.count(Conversation.id)).where(Conversation.agency_id == agency_id)
    ) or 0
    channels = db.scalar(
        select(func.count(WhatsAppChannel.id)).where(WhatsAppChannel.agency_id == agency_id)
    ) or 0
    connected_channels = db.scalar(
        select(func.count(WhatsAppChannel.id)).where(
            WhatsAppChannel.agency_id == agency_id,
            WhatsAppChannel.status == "connected",
        )
    ) or 0
    # Las dependencias cuelgan del cliente y no de la agencia, así que se
    # cuentan atravesando Client.
    departments = db.scalar(
        select(func.count(Department.id))
        .join(Client, Department.client_id == Client.id)
        .where(Client.agency_id == agency_id)
    ) or 0
    recent_agents = db.scalars(
        select(Agent).where(Agent.agency_id == agency_id).order_by(Agent.created_at.desc()).limit(5)
    ).all()
    return {
        "departments": departments,
        "clients": clients,
        "active_clients": active_clients,
        "agents": agents,
        "active_agents": active_agents,
        "conversations": conversations,
        "channels": channels,
        "connected_channels": connected_channels,
        "recent_agents": recent_agents,
    }


@router.get("/metrics", response_model=DashboardMetrics)
def dashboard_metrics(
    days: int = Query(default=14, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agency_id = user.agency_id
    start_date = (now_utc() - timedelta(days=days - 1)).date()
    since = now_utc() - timedelta(days=days)

    # Solo lo intercambiado con el contacto. Las filas kind="activity" —"fulano
    # resolvió la conversación", "fulano la tomó"— viven en la misma tabla y
    # antes entraban en este total, que por eso venía inflado: nadie las mandó
    # ni las recibió. `exchanged_only` es el mismo filtro que usa el hilo.
    exchanged = exchanged_only(
        select(Message.sender_type, func.count(Message.id))
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.agency_id == agency_id, Message.created_at >= since)
    ).group_by(Message.sender_type)
    by_sender = {sender: count for sender, count in db.execute(exchanged).all()}
    # Recibido es lo que escribió el contacto; enviado es todo lo que salió
    # hacia él, lo haya escrito la IA o una persona.
    messages_received = by_sender.get("visitor", 0)
    messages_sent = sum(count for sender, count in by_sender.items() if sender != "visitor")
    messages = messages_received + messages_sent
    human_conversations = db.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.agency_id == agency_id, Conversation.mode == "human", Conversation.created_at >= since
        )
    ) or 0

    channel_rows = db.execute(
        select(Conversation.channel, func.count(Conversation.id))
        .where(Conversation.agency_id == agency_id, Conversation.created_at >= since)
        .group_by(Conversation.channel)
    ).all()
    by_channel = {channel: count for channel, count in channel_rows}

    # New conversations per day over the selected window (zero-filled).
    day = func.date(Conversation.created_at)
    daily_rows = db.execute(
        select(day, func.count(Conversation.id))
        .where(Conversation.agency_id == agency_id, day >= start_date)
        .group_by(day)
    ).all()
    counts = {str(d): c for d, c in daily_rows}
    daily_conversations = [
        {"date": (start_date + timedelta(days=i)).isoformat(), "count": counts.get((start_date + timedelta(days=i)).isoformat(), 0)}
        for i in range(days)
    ]

    top_rows = db.execute(
        select(Agent.id, Agent.name, func.count(Conversation.id))
        .join(Conversation, Conversation.agent_id == Agent.id)
        .where(Agent.agency_id == agency_id, Conversation.created_at >= since)
        .group_by(Agent.id, Agent.name)
        .order_by(func.count(Conversation.id).desc())
        .limit(5)
    ).all()
    top_agents = [{"id": aid, "name": name, "conversations": count} for aid, name, count in top_rows]

    tokens_in, tokens_out = db.execute(
        select(
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        ).where(UsageRecord.agency_id == agency_id, UsageRecord.created_at >= since)
    ).one()
    usage_rows = db.execute(
        select(
            UsageRecord.model,
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        )
        .where(UsageRecord.agency_id == agency_id, UsageRecord.created_at >= since)
        .group_by(UsageRecord.model)
        .order_by((func.sum(UsageRecord.input_tokens) + func.sum(UsageRecord.output_tokens)).desc())
        .limit(6)
    ).all()
    usage_by_model = [{"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens} for model, input_tokens, output_tokens in usage_rows]

    # Conversaciones por dependencia. Un LEFT JOIN desde Department para que
    # una dependencia recién creada aparezca en cero en vez de desaparecer:
    # que todavía no le entró nada es justamente lo que hay que ver.
    department_rows = db.execute(
        select(Department.name, func.count(Conversation.id))
        .select_from(Department)
        .join(Client, Department.client_id == Client.id)
        .outerjoin(
            Conversation,
            (Conversation.department_id == Department.id) & (Conversation.created_at >= since),
        )
        .where(Client.agency_id == agency_id)
        .group_by(Department.id, Department.name)
        .order_by(func.count(Conversation.id).desc(), Department.name)
    ).all()
    by_department = [{"name": name, "conversations": count} for name, count in department_rows]

    # Mediana y no promedio: un puñado de conversaciones que quedaron
    # abandonadas un fin de semana arrastran un promedio hasta volverlo
    # inservible, y lo que se quiere saber es cuánto espera la gente
    # habitualmente. Solo cuentan las que ya tuvieron respuesta.
    first_reply_seconds = db.scalar(
        select(
            func.percentile_cont(0.5).within_group(
                func.extract("epoch", Conversation.first_reply_at - Conversation.created_at)
            )
        ).where(
            Conversation.agency_id == agency_id,
            Conversation.created_at >= since,
            Conversation.first_reply_at.is_not(None),
        )
    )

    return {
        "messages": messages,
        "messages_received": messages_received,
        "messages_sent": messages_sent,
        "by_department": by_department,
        "median_first_reply_seconds": int(first_reply_seconds) if first_reply_seconds is not None else None,
        "human_conversations": human_conversations,
        "by_channel": by_channel,
        "daily_conversations": daily_conversations,
        "top_agents": top_agents,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "usage_by_model": usage_by_model,
    }

import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.log import AgentEvent


def _to_dict(event: AgentEvent) -> dict:
    return {
        "id": event.id,
        "conversation_id": event.conversation_id,
        "agent_name": event.agent_name,
        "event_type": event.event_type,
        "input_summary": event.input_summary,
        "output_summary": event.output_summary,
        "error_message": event.error_message,
        "latency_ms": event.latency_ms,
        "created_at": event.created_at,
    }


def _json(data: dict | None) -> str | None:
    if data is None:
        return None
    return json.dumps(data, ensure_ascii=False, default=str)


async def create_agent_event_db(
    db: AsyncSession,
    *,
    conversation_id: int,
    agent_name: str,
    event_type: str,
    input_summary: dict | str | None = None,
    output_summary: dict | str | None = None,
    error_message: str | None = None,
    latency_ms: int | None = None,
) -> dict:
    event = AgentEvent(
        conversation_id=conversation_id,
        agent_name=agent_name,
        event_type=event_type,
        input_summary=_json(input_summary) if isinstance(input_summary, dict) else input_summary,
        output_summary=_json(output_summary) if isinstance(output_summary, dict) else output_summary,
        error_message=error_message,
        latency_ms=latency_ms,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return _to_dict(event)


async def get_events_by_conversation_db(
    db: AsyncSession,
    conversation_id: int,
) -> list[dict]:
    result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.conversation_id == conversation_id)
        .order_by(AgentEvent.created_at)
    )
    return [_to_dict(e) for e in result.scalars().all()]

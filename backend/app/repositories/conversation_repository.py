from app.mock_data.conversations import MOCK_AGENT_INTENTS, MOCK_CONVERSATIONS
from typing import Optional
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import AgentIntent, Conversation, ConversationMessage

def get_conversation_by_id(conversation_id: int) -> Optional[dict]:
    return next((c for c in MOCK_CONVERSATIONS if c["id"] == conversation_id), None)

def create_conversation(data: dict) -> dict:
    new_id = max(c["id"] for c in MOCK_CONVERSATIONS) + 1
    conv = {"id": new_id, **data}
    MOCK_CONVERSATIONS.append(conv)
    return conv

def update_conversation(conversation_id: int, data: dict) -> Optional[dict]:
    conv = get_conversation_by_id(conversation_id)
    if not conv:
        return None
    conv.update(data)
    return conv

def get_conversation_by_keyword(user_id: int, keyword: str) -> Optional[dict]:
    return next((c for c in MOCK_CONVERSATIONS if c["user_id"] == user_id and c.get("keyword") == keyword), None)


def create_agent_intent(
    conversation_id: int,
    user_id: int,
    raw_user_request: str,
    intent: str,
    keywords: list,
    confidence: float = 0.9,
    needs_clarification: bool = False,
) -> dict:
    new_id = max((i["id"] for i in MOCK_AGENT_INTENTS), default=0) + 1
    entry = {
        "id": new_id,
        "conversation_id": conversation_id,
        "user_id": user_id,
        "raw_user_request": raw_user_request,
        "intent": intent,
        "intent_type": intent,
        "extracted_keywords": ", ".join(keywords),
        "confidence": confidence,
        "needs_clarification": needs_clarification,
        "created_at": datetime.now().isoformat(),
    }
    MOCK_AGENT_INTENTS.append(entry)
    return entry


def _conversation_to_dict(conversation: Conversation) -> dict:
    """ORM Conversation을 기존 agent_service가 쓰는 dict 형태로 변환한다."""
    return {
        "id": conversation.id,
        "user_id": conversation.user_id,
        "langgraph_thread_id": conversation.langgraph_thread_id,
        "status": conversation.status,
        "stage": conversation.stage,
        "keyword": conversation.keyword,
        "summary": conversation.summary,
        "summary_message_count": conversation.summary_message_count,
        "started_at": conversation.started_at,
        "ended_at": conversation.ended_at,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


async def get_conversation_by_id_db(db: AsyncSession, conversation_id: int) -> Optional[dict]:
    """DB에서 대화 세션을 조회한다."""
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        return None
    return _conversation_to_dict(conversation)


async def create_conversation_db(db: AsyncSession, data: dict) -> dict:
    """새 대화 세션을 만들고 LangGraph thread id를 비즈니스 대화 id와 연결한다."""
    conversation = Conversation(
        user_id=data["user_id"],
        langgraph_thread_id=data.get("langgraph_thread_id"),
        status=data["status"],
        stage=data["stage"],
        keyword=data.get("keyword"),
        summary=data.get("summary"),
        summary_message_count=data.get("summary_message_count"),
        started_at=data.get("started_at") or datetime.now(UTC),
        ended_at=data.get("ended_at"),
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    if not conversation.langgraph_thread_id:
        conversation.langgraph_thread_id = str(conversation.id)
        await db.commit()
        await db.refresh(conversation)

    return _conversation_to_dict(conversation)


async def update_conversation_db(db: AsyncSession, conversation_id: int, data: dict) -> Optional[dict]:
    """DB 대화 세션의 상태, stage, 요약 정보를 갱신한다."""
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        return None

    for field_name, field_value in data.items():
        if hasattr(conversation, field_name):
            setattr(conversation, field_name, field_value)

    await db.commit()
    await db.refresh(conversation)
    return _conversation_to_dict(conversation)


async def create_conversation_message_db(
    db: AsyncSession,
    conversation_id: int,
    role: str,
    content: str,
) -> dict:
    """사용자/assistant/tool 메시지 원문을 DB에 저장한다."""
    message = ConversationMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
    }


async def create_agent_intent_db(db: AsyncSession, data: dict) -> dict:
    """Intent Agent의 사용자 요청 해석 결과를 DB에 저장한다."""
    intent = AgentIntent(
        conversation_id=data["conversation_id"],
        user_id=data["user_id"],
        raw_user_request=data["raw_user_request"],
        intent=data["intent"],
        intent_type=data["intent_type"],
        stage=data.get("stage"),
        pending_action_type=data.get("pending_action_type"),
        target_category=data.get("target_category"),
        target_product_name=data.get("target_product_name"),
        extracted_keywords=data.get("extracted_keywords"),
        confidence=data.get("confidence"),
        needs_clarification=data.get("needs_clarification"),
        clarification_reason=data.get("clarification_reason"),
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)
    return {
        "id": intent.id,
        "conversation_id": intent.conversation_id,
        "user_id": intent.user_id,
        "raw_user_request": intent.raw_user_request,
        "intent": intent.intent,
        "intent_type": intent.intent_type,
        "stage": intent.stage,
        "pending_action_type": intent.pending_action_type,
        "target_category": intent.target_category,
        "target_product_name": intent.target_product_name,
        "extracted_keywords": intent.extracted_keywords,
        "confidence": intent.confidence,
        "needs_clarification": intent.needs_clarification,
        "clarification_reason": intent.clarification_reason,
        "created_at": intent.created_at,
    }

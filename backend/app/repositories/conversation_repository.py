from app.mock_data.conversations import MOCK_CONVERSATIONS, MOCK_AGENT_INTENTS
from typing import Optional
from datetime import datetime

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

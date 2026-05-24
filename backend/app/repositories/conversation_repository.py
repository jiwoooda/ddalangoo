from app.mock_data.conversations import MOCK_CONVERSATIONS
from typing import Optional

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

from app.mock_data.purchase_histories import MOCK_PURCHASE_HISTORIES
from typing import Optional, List
from datetime import datetime

def get_histories_by_user_id(user_id: int) -> List[dict]:
    return [h for h in MOCK_PURCHASE_HISTORIES if h["user_id"] == user_id]

def get_history_by_id(history_id: int) -> Optional[dict]:
    return next((h for h in MOCK_PURCHASE_HISTORIES if h["id"] == history_id), None)

def get_history_by_keyword(user_id: int, keyword: str) -> Optional[dict]:
    matches = [h for h in MOCK_PURCHASE_HISTORIES if h["user_id"] == user_id and h.get("keyword") == keyword]
    return matches[0] if matches else None

def create_history(data: dict) -> dict:
    new_id = max((h["id"] for h in MOCK_PURCHASE_HISTORIES), default=0) + 1
    entry = {
        "id": new_id,
        "purchased_at": datetime.now().isoformat(),
        **data,
    }
    MOCK_PURCHASE_HISTORIES.append(entry)
    return entry

import os
import json
from typing import Optional, List
from datetime import datetime

_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_data", "purchase_histories.json")


def _load() -> List[dict]:
    with open(_JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(data: List[dict]) -> None:
    with open(_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


MOCK_PURCHASE_HISTORIES: List[dict] = _load()


def get_histories_by_user_id(user_id: int) -> List[dict]:
    return [h for h in MOCK_PURCHASE_HISTORIES if h["user_id"] == user_id]

def get_history_by_id(history_id: int) -> Optional[dict]:
    return next((h for h in MOCK_PURCHASE_HISTORIES if h["id"] == history_id), None)

def get_history_by_keyword(user_id: int, keyword: str) -> Optional[dict]:
    matches = [h for h in MOCK_PURCHASE_HISTORIES if h["user_id"] == user_id and h.get("keyword") == keyword]
    return matches[0] if matches else None

def get_history_by_order_item(
    order_id: int,
    product_id: Optional[int],
    product_option_id: Optional[int] = None,
    option_text: Optional[str] = None,
) -> Optional[dict]:
    return next(
        (
            h for h in MOCK_PURCHASE_HISTORIES
            if h.get("order_id") == order_id
            and h.get("product_id") == product_id
            and (
                h.get("product_option_id") == product_option_id
                or h.get("option_text") == option_text
            )
        ),
        None,
    )

def create_history(data: dict) -> dict:
    new_id = max((h["id"] for h in MOCK_PURCHASE_HISTORIES), default=0) + 1
    entry = {
        "id": new_id,
        "purchased_at": datetime.now().isoformat(),
        **data,
    }
    MOCK_PURCHASE_HISTORIES.append(entry)
    _save(MOCK_PURCHASE_HISTORIES)
    return entry

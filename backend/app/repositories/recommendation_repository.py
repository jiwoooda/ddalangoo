from app.mock_data.recommendations import MOCK_RECOMMENDATIONS, MOCK_RECOMMENDATION_ITEMS
from typing import Optional, List


def _next_id(rows: list[dict]) -> int:
    return max((row["id"] for row in rows), default=0) + 1

def get_recommendation_by_id(recommendation_id: int) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["id"] == recommendation_id), None)

def get_recommendation_by_conversation_id(conversation_id: int) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["conversation_id"] == conversation_id), None)

def get_items_by_recommendation_id(recommendation_id: int) -> List[dict]:
    return [i for i in MOCK_RECOMMENDATION_ITEMS if i["recommendation_id"] == recommendation_id]

def get_recommendation_by_keyword(keyword: str) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["keyword"] == keyword), None)


def create_recommendation(data: dict) -> dict:
    recommendation = {
        "id": _next_id(MOCK_RECOMMENDATIONS),
        **data,
    }
    MOCK_RECOMMENDATIONS.append(recommendation)
    return recommendation


def create_recommendation_item(recommendation_id: int, data: dict) -> dict:
    item = {
        "id": _next_id(MOCK_RECOMMENDATION_ITEMS),
        "recommendation_id": recommendation_id,
        **data,
    }
    MOCK_RECOMMENDATION_ITEMS.append(item)
    return item

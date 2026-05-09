from app.mock_data.recommendations import MOCK_RECOMMENDATIONS, MOCK_RECOMMENDATION_ITEMS
from typing import Optional, List

def get_recommendation_by_id(recommendation_id: int) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["id"] == recommendation_id), None)

def get_recommendation_by_conversation_id(conversation_id: int) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["conversation_id"] == conversation_id), None)

def get_items_by_recommendation_id(recommendation_id: int) -> List[dict]:
    return [i for i in MOCK_RECOMMENDATION_ITEMS if i["recommendation_id"] == recommendation_id]

def get_recommendation_by_keyword(keyword: str) -> Optional[dict]:
    return next((r for r in MOCK_RECOMMENDATIONS if r["keyword"] == keyword), None)

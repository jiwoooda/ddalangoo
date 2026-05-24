from app.repositories import recommendation_repository
from app.schemas.recommendation import RecommendationResponse, RecommendationItemDetail
from fastapi import HTTPException

def _item_to_detail(i: dict) -> RecommendationItemDetail:
    return RecommendationItemDetail(
        recommendationItemId=i["id"], rank=i["rank"], productName=i["product_name"],
        brand=i.get("brand"), price=i["price"], optionText=i.get("option_text"),
        deliveryInfo=i.get("delivery_info"), imageUrl=i.get("image_url"),
        reason=i.get("reason"), isSelected=i.get("is_selected", False),
        isOrderable=i["is_orderable"], orderBlockReason=i.get("order_block_reason")
    )

def get_recommendation(recommendation_id: int) -> RecommendationResponse:
    rec = recommendation_repository.get_recommendation_by_id(recommendation_id)
    if not rec:
        raise HTTPException(status_code=404, detail={"category": "RECOMMENDATION_ERROR", "code": "RECOMMENDATION_NOT_FOUND", "message": "추천을 찾을 수 없습니다."})
    items = recommendation_repository.get_items_by_recommendation_id(recommendation_id)
    return RecommendationResponse(
        recommendationId=rec["id"], conversationId=rec["conversation_id"],
        status=rec.get("status"), summary=rec.get("summary"),
        items=[_item_to_detail(i) for i in items]
    )

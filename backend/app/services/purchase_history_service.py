from app.repositories import purchase_history_repository, user_repository
from app.schemas.purchase_history import PurchaseHistoryItem, PurchaseHistoryListResponse, PurchaseHistoryDetailResponse
from fastapi import HTTPException
from typing import Optional

def _to_item(h: dict) -> PurchaseHistoryItem:
    return PurchaseHistoryItem(
        purchaseHistoryId=h["id"], productName=h["product_name"], brand=h.get("brand"),
        category=h.get("category"), optionText=h.get("option_text"),
        priceAtPurchase=h.get("price_at_purchase", 0), quantity=h.get("quantity", 1),
        totalPrice=h.get("total_price", 0), platform=h.get("platform"),
        purchasedAt=h["purchased_at"], satisfaction=h.get("satisfaction_score"), memo=h.get("memo")
    )

def get_histories(user_id: int, keyword: Optional[str] = None, category: Optional[str] = None, limit: Optional[int] = None) -> PurchaseHistoryListResponse:
    if not user_repository.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    histories = purchase_history_repository.get_histories_by_user_id(user_id)
    if keyword:
        histories = [h for h in histories if keyword in h["product_name"]]
    if category:
        histories = [h for h in histories if h.get("category") == category]
    if limit:
        histories = histories[:limit]
    return PurchaseHistoryListResponse(userId=user_id, histories=[_to_item(h) for h in histories])

def get_history(history_id: int) -> PurchaseHistoryDetailResponse:
    h = purchase_history_repository.get_history_by_id(history_id)
    if not h:
        raise HTTPException(status_code=404, detail={"category": "HISTORY_ERROR", "code": "HISTORY_NOT_FOUND", "message": "구매 이력을 찾을 수 없습니다."})
    return PurchaseHistoryDetailResponse(
        purchaseHistoryId=h["id"], userId=h["user_id"], productId=h["product_id"],
        productOptionId=h.get("product_option_id"), platform=h.get("platform"),
        productName=h["product_name"], brand=h.get("brand"), category=h.get("category"),
        optionText=h.get("option_text"), priceAtPurchase=h.get("price_at_purchase", 0),
        quantity=h.get("quantity", 1), totalPrice=h.get("total_price", 0),
        purchasedAt=h["purchased_at"], satisfaction=h.get("satisfaction_score"), memo=h.get("memo")
    )

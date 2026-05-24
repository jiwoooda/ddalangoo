from app.repositories import purchase_history_repository, user_repository
from app.schemas.purchase_history import PurchaseHistoryItem, PurchaseHistoryListResponse, PurchaseHistoryDetailResponse
from fastapi import HTTPException
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession


def _iso(v) -> Optional[str]:
    """datetime → ISO 8601 문자열. None이면 None, 이미 str이면 그대로."""
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _to_item(h: dict) -> PurchaseHistoryItem:
    return PurchaseHistoryItem(
        purchaseHistoryId=h["id"], productName=h["product_name"], brand=h.get("brand"),
        category=h.get("category"), optionText=h.get("option_text"),
        priceAtPurchase=h.get("price_at_purchase", 0), quantity=h.get("quantity", 1),
        totalPrice=h.get("total_price", 0), platform=h.get("platform"),
        purchasedAt=_iso(h.get("purchased_at")), satisfaction=h.get("satisfaction_score"), memo=h.get("memo")
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
        purchasedAt=_iso(h.get("purchased_at")), satisfaction=h.get("satisfaction_score"), memo=h.get("memo")
    )


async def get_histories_db(
    db: AsyncSession,
    user_id: int,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
) -> PurchaseHistoryListResponse:
    """DB에서 사용자 구매 이력을 조회한다."""
    if not await user_repository.get_user_by_id_db(db, user_id):
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    histories = await purchase_history_repository.get_histories_by_user_id_db(
        db,
        user_id,
        keyword=keyword,
        category=category,
        limit=limit,
    )
    return PurchaseHistoryListResponse(userId=user_id, histories=[_to_item(h) for h in histories])


async def get_history_db(db: AsyncSession, history_id: int) -> PurchaseHistoryDetailResponse:
    """DB에서 구매 이력 단건을 조회한다."""
    h = await purchase_history_repository.get_history_by_id_db(db, history_id)
    if not h:
        raise HTTPException(status_code=404, detail={"category": "HISTORY_ERROR", "code": "HISTORY_NOT_FOUND", "message": "구매 이력을 찾을 수 없습니다."})
    return PurchaseHistoryDetailResponse(
        purchaseHistoryId=h["id"], userId=h["user_id"], productId=h["product_id"] or 0,
        productOptionId=h.get("product_option_id"), platform=h.get("platform"),
        productName=h["product_name"], brand=h.get("brand"), category=h.get("category"),
        optionText=h.get("option_text"), priceAtPurchase=h.get("price_at_purchase", 0),
        quantity=h.get("quantity", 1), totalPrice=h.get("total_price", 0),
        purchasedAt=_iso(h.get("purchased_at")), satisfaction=h.get("satisfaction_score"), memo=h.get("memo")
    )

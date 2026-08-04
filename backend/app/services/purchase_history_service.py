from app.repositories import order_repository, purchase_history_repository, user_repository
from app.schemas.purchase_history import (
    AccessibilityPurchaseHistoryImportItem,
    AccessibilityPurchaseHistoryImportResponse,
    PurchaseHistoryItem,
    PurchaseHistoryListResponse,
    PurchaseHistoryDetailResponse,
)
from fastapi import HTTPException
from datetime import UTC, datetime
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession


def _iso(v) -> Optional[str]:
    """datetime → ISO 8601 문자열. None이면 None, 이미 str이면 그대로."""
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _parse_purchase_date(value: Optional[str]) -> Optional[datetime]:
    """Accessibility에서 온 날짜 문자열을 DB에 저장할 datetime으로 바꾼다."""
    if not value:
        return None

    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass

    for date_format in ("%Y-%m-%d", "%Y.%m.%d", "%Y. %m. %d", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(text, date_format)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue

    match = re.search(r"(20\d{2})\D+(\d{1,2})\D+(\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(group) for group in match.groups())
    return datetime(year, month, day, tzinfo=UTC)


def _clean_product_name(value: Optional[str]) -> Optional[str]:
    """Agent가 재구매 근거로 써도 되는 상품명만 통과시킨다."""
    product_name = (value or "").strip()
    if not product_name or product_name == "상품명 확인 필요":
        return None
    return product_name


def _normalize_accessibility_item(
    item: AccessibilityPurchaseHistoryImportItem,
) -> tuple[dict | None, dict | None]:
    """Flutter/Android DTO를 purchase_histories insert용 dict로 변환한다."""
    product_name = _clean_product_name(item.productName)
    quantity = item.quantity or 1
    price = item.price
    purchased_at = _parse_purchase_date(item.purchaseDate)

    missing_fields = []
    if not item.platform:
        missing_fields.append("platform")
    if not product_name:
        missing_fields.append("productName")
    if price is None:
        missing_fields.append("price")
    if quantity <= 0:
        missing_fields.append("quantity")
    if purchased_at is None:
        missing_fields.append("purchaseDate")

    if missing_fields:
        return None, {
            "reason": "cannot_fill_purchase_histories_required_columns",
            "missingFields": missing_fields,
            "productName": item.productName,
            "platform": item.platform,
            "raw": item.raw,
        }

    metadata = {
        "sourceType": item.sourceType or "accessibility",
        "deliveryStatus": item.deliveryStatus,
        "deliveryType": item.deliveryType,
        "imageUrl": item.imageUrl,
        "raw": item.raw,
    }
    selected_options = {
        "accessibility": {
            key: value
            for key, value in metadata.items()
            if value not in (None, "", {})
        }
    }

    return {
        "external_order_id": item.orderNumber,
        "external_product_order_id": item.productOrderId,
        "platform": item.platform,
        "keyword": item.keyword or product_name,
        "product_name": product_name,
        "option_text": item.optionText,
        "brand": item.brand,
        "category": item.category,
        "price_at_purchase": price,
        "product_url": item.productUrl,
        "selected_options": selected_options,
        "quantity": quantity,
        "total_price": price * quantity,
        "purchased_at": purchased_at,
        "memo": item.deliveryStatus,
        "raw": item.raw,
    }, None


def create_histories_from_order(conversation_id: int, user_id: int) -> dict:
    order = order_repository.get_order_by_conversation_id(conversation_id)
    if not order:
        return {"success": False, "error": "order not found", "count": 0, "history_ids": []}

    items = order_repository.get_order_items_by_order_id(order["id"])
    if not items:
        return {"success": False, "error": "order_items empty", "count": 0, "history_ids": []}

    saved = []
    skipped = []
    for item in items:
        existing = purchase_history_repository.get_history_by_order_item(
            order_id=order["id"],
            product_id=item.get("product_id"),
            product_option_id=item.get("product_option_id"),
            option_text=item.get("option_text"),
        )
        if existing:
            skipped.append(existing["id"])
            continue

        history = purchase_history_repository.create_history({
            "user_id": user_id,
            "conversation_id": conversation_id,
            "order_id": order["id"],
            "product_id": item.get("product_id"),
            "product_option_id": item.get("product_option_id"),
            "product_name": item.get("product_name", ""),
            "option_text": item.get("option_text"),
            "selected_options": item.get("selected_options") or {},
            "product_url": item.get("product_url"),
            "price_at_purchase": item.get("unit_price", 0),
            "quantity": item.get("quantity", 1),
            "total_price": item.get("total_price", 0),
            "platform": order.get("platform", "naver"),
        })
        saved.append(history["id"])

    return {
        "success": True,
        "count": len(saved),
        "history_ids": saved,
        "skipped_existing_ids": skipped,
    }


async def create_histories_from_order_db(
    db: AsyncSession,
    conversation_id: int,
    user_id: int,
    payment_id: int | None = None,
) -> dict:
    """DB order/order_items를 purchase_histories로 복사한다."""
    order = await order_repository.get_order_by_conversation_id_db(db, conversation_id)
    if not order or order.get("user_id") != user_id:
        return {"success": False, "error": "order not found", "count": 0, "history_ids": []}

    histories = await purchase_history_repository.create_histories_from_order_db(
        db,
        order_id=order["id"],
        payment_id=payment_id,
    )
    return {
        "success": True,
        "count": len(histories),
        "history_ids": [history["id"] for history in histories],
        "skipped_existing_ids": [],
    }


async def create_histories_from_accessibility_db(
    db: AsyncSession,
    user_id: int,
    items: list[AccessibilityPurchaseHistoryImportItem],
) -> AccessibilityPurchaseHistoryImportResponse:
    """
    Accessibility 자동화가 수집한 구매이력을 Agent용 purchase_histories로 저장한다.

    purchase_histories의 non-null 컬럼을 채울 수 없는 항목은 저장하지 않고 skip한다.
    """
    if not await user_repository.get_user_by_id_db(db, user_id):
        raise HTTPException(
            status_code=404,
            detail={
                "category": "USER_ERROR",
                "code": "USER_NOT_FOUND",
                "message": "사용자를 찾을 수 없습니다.",
            },
        )

    normalized_items: list[dict] = []
    skipped_items: list[dict] = []
    for index, item in enumerate(items):
        normalized, skipped = _normalize_accessibility_item(item)
        if skipped:
            skipped["index"] = index
            skipped_items.append(skipped)
            continue
        if normalized:
            normalized_items.append(normalized)

    histories, repository_skipped = await purchase_history_repository.create_histories_from_accessibility_db(
        db,
        user_id=user_id,
        items=normalized_items,
    )
    skipped_items.extend(repository_skipped)

    return AccessibilityPurchaseHistoryImportResponse(
        success=True,
        count=len(histories),
        historyIds=[history["id"] for history in histories],
        skippedCount=len(skipped_items),
        skippedItems=skipped_items,
    )

def _to_item(h: dict) -> PurchaseHistoryItem:
    return PurchaseHistoryItem(
        purchaseHistoryId=h["id"], productName=h["product_name"], brand=h.get("brand"),
        category=h.get("category"), optionText=h.get("option_text"),
        selectedOptions=h.get("selected_options"), productUrl=h.get("product_url"),
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
        selectedOptions=h.get("selected_options"), productUrl=h.get("product_url"),
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
        purchaseHistoryId=h["id"], userId=h["user_id"], productId=h["product_id"],
        productOptionId=h.get("product_option_id"), platform=h.get("platform"),
        productName=h["product_name"], brand=h.get("brand"), category=h.get("category"),
        optionText=h.get("option_text"), priceAtPurchase=h.get("price_at_purchase", 0),
        quantity=h.get("quantity", 1), totalPrice=h.get("total_price", 0),
        purchasedAt=_iso(h.get("purchased_at")), satisfaction=h.get("satisfaction_score"), memo=h.get("memo")
    )

from app.mock_data.purchase_histories import MOCK_PURCHASE_HISTORIES
from typing import Optional, List
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.purchase_history import PurchaseHistory

def get_histories_by_user_id(user_id: int) -> List[dict]:
    return [h for h in MOCK_PURCHASE_HISTORIES if h["user_id"] == user_id]

def get_history_by_id(history_id: int) -> Optional[dict]:
    return next((h for h in MOCK_PURCHASE_HISTORIES if h["id"] == history_id), None)

def get_history_by_keyword(user_id: int, keyword: str) -> Optional[dict]:
    matches = [h for h in MOCK_PURCHASE_HISTORIES if h["user_id"] == user_id and h.get("keyword") == keyword]
    return matches[0] if matches else None


def _history_to_dict(history: PurchaseHistory) -> dict:
    """ORM PurchaseHistory를 기존 API 응답 매핑용 dict로 변환한다."""
    return {
        "id": history.id,
        "user_id": history.user_id,
        "product_id": history.product_id,
        "product_option_id": history.product_option_id,
        "conversation_id": history.conversation_id,
        "order_id": history.order_id,
        "payment_id": history.payment_id,
        "platform": history.platform,
        "keyword": history.keyword,
        "product_name_snapshot": history.product_name_snapshot,
        "product_name": history.product_name_snapshot,
        "option_snapshot": history.option_snapshot,
        "option_text": history.option_snapshot,
        "brand_snapshot": history.brand_snapshot,
        "brand": history.brand_snapshot,
        "category_snapshot": history.category_snapshot,
        "category": history.category_snapshot,
        "price_at_purchase": history.price_at_purchase,
        "product_url_snapshot": history.product_url_snapshot,
        "selected_options": history.selected_options,
        "quantity": history.quantity,
        "total_price": history.total_price,
        "purchased_at": history.purchased_at,
        "satisfaction": history.satisfaction,
        "satisfaction_score": history.satisfaction,
        "memo": history.memo,
        "created_at": history.created_at,
    }


async def get_histories_by_user_id_db(
    db: AsyncSession,
    user_id: int,
    keyword: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """DB에서 사용자 구매 이력을 조회한다."""
    stmt = select(PurchaseHistory).where(PurchaseHistory.user_id == user_id)
    if keyword:
        keyword_pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                PurchaseHistory.keyword.ilike(keyword_pattern),
                PurchaseHistory.product_name_snapshot.ilike(keyword_pattern),
                PurchaseHistory.category_snapshot.ilike(keyword_pattern),
            )
        )
    if category:
        stmt = stmt.where(PurchaseHistory.category_snapshot == category)
    stmt = stmt.order_by(PurchaseHistory.purchased_at.desc())
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return [_history_to_dict(history) for history in result.scalars().all()]


async def get_history_by_id_db(db: AsyncSession, history_id: int) -> Optional[dict]:
    """DB에서 구매 이력 단건을 조회한다."""
    history = await db.get(PurchaseHistory, history_id)
    if not history:
        return None
    return _history_to_dict(history)


async def get_history_by_keyword_db(
    db: AsyncSession,
    user_id: int,
    keyword: str,
) -> Optional[dict]:
    """재구매 요청에서 쓸 keyword 기반 구매 이력 조회다."""
    histories = await get_histories_by_user_id_db(db, user_id, keyword=keyword, limit=1)
    return histories[0] if histories else None


async def create_histories_from_order_db(
    db: AsyncSession,
    *,
    order_id: int,
    payment_id: int | None = None,
) -> list[dict]:
    """
    결제 완료 후 order_items snapshot을 purchase_histories로 복사한다.

    purchase_histories는 재구매 검색용 read model이므로, 이미 같은 order_id의
    이력이 있으면 중복 생성하지 않고 기존 이력을 반환한다.
    """
    existing_result = await db.execute(
        select(PurchaseHistory).where(PurchaseHistory.order_id == order_id)
    )
    existing = existing_result.scalars().all()
    if existing:
        return [_history_to_dict(history) for history in existing]

    order = await db.get(Order, order_id)
    if not order:
        raise ValueError("구매 이력을 만들 주문을 찾을 수 없습니다.")

    item_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id.asc())
    )
    order_items = item_result.scalars().all()
    if not order_items:
        raise ValueError("구매 이력을 만들 주문 상품이 없습니다.")

    purchased_at = order.ordered_at or datetime.now(UTC)
    created_histories: list[PurchaseHistory] = []

    for item in order_items:
        product = await db.get(Product, item.product_id)
        history = PurchaseHistory(
            user_id=order.user_id,
            product_id=item.product_id,
            product_option_id=item.product_option_id,
            conversation_id=order.conversation_id,
            order_id=order.id,
            payment_id=payment_id,
            external_product_order_id=item.external_product_order_id,
            platform=order.platform,
            keyword=(product.normalized_name if product else None),
            product_name_snapshot=item.product_name_snapshot,
            option_snapshot=item.option_snapshot,
            brand_snapshot=(product.brand if product else None),
            category_snapshot=(product.category if product else None),
            price_at_purchase=item.unit_price,
            product_url_snapshot=item.product_url_snapshot,
            selected_options=item.selected_options,
            quantity=item.quantity,
            total_price=item.total_price,
            purchased_at=purchased_at,
        )
        db.add(history)
        created_histories.append(history)

    await db.commit()
    for history in created_histories:
        await db.refresh(history)

    return [_history_to_dict(history) for history in created_histories]

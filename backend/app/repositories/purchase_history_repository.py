from datetime import UTC, datetime
import json
import os
from typing import Optional, List

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.purchase_history import PurchaseHistory

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
        "product_url": history.product_url_snapshot,
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


async def update_satisfaction_db(
    db: AsyncSession,
    history_id: int,
    user_id: int,
    satisfaction_score: int | None,
    memo: str | None = None,
) -> bool:
    """만족도 체크인(satisfaction_checkin.py) 결과를 구매 이력 하나에 기록한다.
    mock_update_purchase_satisfaction과 동일한 시맨틱 — satisfaction_score는
    None이어도 그대로 덮어쓰고, memo는 None이면(응답에 별도 코멘트가 없었으면)
    기존 값을 유지한다. mock이 user_id별 딕셔너리에서만 찾는 것과 동일하게
    history.user_id도 함께 검증한다 — 다른 사용자의 구매 이력을 잘못된
    purchase_history_id로 덮어쓰지 않기 위함. 대상을 못 찾으면(또는 소유자가
    다르면) False."""
    history = await db.get(PurchaseHistory, history_id)
    if not history or history.user_id != user_id:
        return False
    history.satisfaction = satisfaction_score
    if memo is not None:
        history.memo = memo
    await db.commit()
    return True


async def get_history_by_keyword_db(
    db: AsyncSession,
    user_id: int,
    keyword: str,
) -> Optional[dict]:
    """재구매 요청에서 쓸 keyword 기반 구매 이력 조회다."""
    histories = await get_histories_by_user_id_db(db, user_id, keyword=keyword, limit=1)
    return histories[0] if histories else None


async def get_histories_by_keywords_db(
    db: AsyncSession,
    user_id: int,
    *,
    keywords: list[str],
    limit: int = 5,
) -> list[dict]:
    """Agent 재구매 검색용으로 여러 keyword에 맞는 구매이력을 조회한다."""
    normalized_keywords = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
    if not normalized_keywords:
        return await get_histories_by_user_id_db(db, user_id, limit=limit)

    conditions = []
    for keyword in normalized_keywords:
        keyword_pattern = f"%{keyword}%"
        conditions.extend(
            [
                PurchaseHistory.keyword.ilike(keyword_pattern),
                PurchaseHistory.product_name_snapshot.ilike(keyword_pattern),
                PurchaseHistory.brand_snapshot.ilike(keyword_pattern),
                PurchaseHistory.category_snapshot.ilike(keyword_pattern),
                PurchaseHistory.option_snapshot.ilike(keyword_pattern),
            ]
        )

    stmt = (
        select(PurchaseHistory)
        .where(PurchaseHistory.user_id == user_id)
        .where(or_(*conditions))
        .order_by(PurchaseHistory.purchased_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [_history_to_dict(history) for history in result.scalars().all()]


async def get_external_history_db(
    db: AsyncSession,
    *,
    user_id: int,
    platform: str | None,
    external_order_id: str | None = None,
    external_product_order_id: str | None = None,
    product_name: str | None = None,
    purchased_at: datetime | None = None,
) -> Optional[dict]:
    """외부 플랫폼에서 수집한 구매이력 중복 여부를 확인한다."""
    stmt = select(PurchaseHistory).where(PurchaseHistory.user_id == user_id)
    if platform:
        stmt = stmt.where(PurchaseHistory.platform == platform)

    if external_order_id and external_product_order_id:
        stmt = stmt.where(PurchaseHistory.external_order_id == external_order_id)
        stmt = stmt.where(PurchaseHistory.external_product_order_id == external_product_order_id)
    elif external_order_id and product_name:
        stmt = stmt.where(PurchaseHistory.external_order_id == external_order_id)
        stmt = stmt.where(PurchaseHistory.product_name_snapshot == product_name)
    elif product_name and purchased_at:
        stmt = stmt.where(PurchaseHistory.product_name_snapshot == product_name)
        stmt = stmt.where(PurchaseHistory.purchased_at == purchased_at)
    else:
        return None

    result = await db.execute(stmt.limit(1))
    history = result.scalars().first()
    return _history_to_dict(history) if history else None


async def get_history_by_order_item_db(
    db: AsyncSession,
    *,
    order_id: int,
    product_id: int | None,
    product_option_id: int | None = None,
    option_text: str | None = None,
) -> Optional[dict]:
    """order_item 기준으로 이미 생성된 구매이력이 있는지 확인한다."""
    stmt = select(PurchaseHistory).where(
        PurchaseHistory.order_id == order_id,
        PurchaseHistory.product_id == product_id,
    )
    if product_option_id is not None:
        stmt = stmt.where(PurchaseHistory.product_option_id == product_option_id)
    else:
        stmt = stmt.where(PurchaseHistory.product_option_id.is_(None))
        if option_text is not None:
            stmt = stmt.where(PurchaseHistory.option_snapshot == option_text)

    result = await db.execute(stmt.limit(1))
    history = result.scalars().first()
    return _history_to_dict(history) if history else None


async def create_histories_from_order_db(
    db: AsyncSession,
    *,
    order_id: int,
    payment_id: int | None = None,
) -> list[dict]:
    """
    결제 완료 후 order_items snapshot을 purchase_histories로 복사한다.

    purchase_histories는 재구매 검색용 read model이다.
    같은 order_id + product_id + option 조합이 이미 있으면 해당 item은 skip한다.
    """
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
    existing_histories: list[dict] = []

    for item in order_items:
        existing = await get_history_by_order_item_db(
            db,
            order_id=order.id,
            product_id=item.product_id,
            product_option_id=item.product_option_id,
            option_text=item.option_snapshot,
        )
        if existing:
            existing_histories.append(existing)
            continue

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

    return existing_histories + [_history_to_dict(history) for history in created_histories]


async def create_histories_from_accessibility_db(
    db: AsyncSession,
    *,
    user_id: int,
    items: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Accessibility 자동화로 수집한 외부 플랫폼 구매이력을 purchase_histories에 저장한다.

    product_id/order_id 없이도 Agent가 재구매 근거로 읽을 수 있도록 snapshot 필드만 채운다.
    """
    created_histories: list[PurchaseHistory] = []
    created_history_dicts: list[dict] = []
    skipped_items: list[dict] = []

    for index, item in enumerate(items):
        missing_fields = [
            field_name
            for field_name in ("platform", "product_name", "price_at_purchase", "quantity", "total_price", "purchased_at")
            if item.get(field_name) in (None, "")
        ]
        if missing_fields:
            skipped_items.append(
                {
                    "index": index,
                    "reason": "missing_required_fields",
                    "missingFields": missing_fields,
                    "raw": item.get("raw") or {},
                }
            )
            continue

        existing = await get_external_history_db(
            db,
            user_id=user_id,
            platform=item.get("platform"),
            external_order_id=item.get("external_order_id"),
            external_product_order_id=item.get("external_product_order_id"),
            product_name=item.get("product_name"),
            purchased_at=item.get("purchased_at"),
        )
        if existing:
            continue

        history = PurchaseHistory(
            user_id=user_id,
            external_order_id=item.get("external_order_id"),
            external_product_order_id=item.get("external_product_order_id"),
            platform=item.get("platform"),
            keyword=item.get("keyword") or item.get("product_name"),
            product_name_snapshot=item["product_name"],
            option_snapshot=item.get("option_text"),
            brand_snapshot=item.get("brand"),
            category_snapshot=item.get("category"),
            price_at_purchase=item["price_at_purchase"],
            product_url_snapshot=item.get("product_url"),
            selected_options=item.get("selected_options"),
            quantity=item["quantity"],
            total_price=item["total_price"],
            purchased_at=item["purchased_at"],
            memo=item.get("memo"),
        )
        db.add(history)
        created_histories.append(history)

    await db.commit()
    for history in created_histories:
        await db.refresh(history)
        created_history_dicts.append(_history_to_dict(history))

    return created_history_dicts, skipped_items

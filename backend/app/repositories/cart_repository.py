from typing import Optional, List
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mock_data.carts import MOCK_CARTS, MOCK_CART_ITEMS
from app.models.order import Cart, CartItem
from app.models.recommendation import RecommendationItem

def get_cart_by_user_id(user_id: int) -> Optional[dict]:
    return next((c for c in MOCK_CARTS if c["user_id"] == user_id), None)

def get_cart_items_by_cart_id(cart_id: int) -> List[dict]:
    return [i for i in MOCK_CART_ITEMS if i["cart_id"] == cart_id]

def add_cart_item(cart_id: int, data: dict) -> dict:
    new_id = max((i["id"] for i in MOCK_CART_ITEMS), default=0) + 1
    item = {"id": new_id, "cart_id": cart_id, **data}
    MOCK_CART_ITEMS.append(item)
    return item

def delete_cart_item(cart_id: int, cart_item_id: int) -> bool:
    item = next((i for i in MOCK_CART_ITEMS if i["cart_id"] == cart_id and i["id"] == cart_item_id), None)
    if not item:
        return False
    MOCK_CART_ITEMS.remove(item)
    return True


def _cart_to_dict(cart: Cart) -> dict:
    """ORM Cart를 API/service에서 쓰기 쉬운 dict로 변환한다."""
    return {
        "id": cart.id,
        "user_id": cart.user_id,
        "conversation_id": cart.conversation_id,
        "status": cart.status,
        "created_at": cart.created_at,
        "updated_at": cart.updated_at,
    }


def _cart_item_to_dict(item: CartItem) -> dict:
    """ORM CartItem snapshot을 기존 dict 형태로 변환한다."""
    return {
        "id": item.id,
        "cart_id": item.cart_id,
        "product_id": item.product_id,
        "product_option_id": item.product_option_id,
        "recommendation_item_id": item.recommendation_item_id,
        "quantity": item.quantity,
        "unit_price_snapshot": item.unit_price_snapshot,
        "product_name_snapshot": item.product_name_snapshot,
        "option_snapshot": item.option_snapshot,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def get_active_cart_by_user_id_db(
    db: AsyncSession,
    user_id: int,
    conversation_id: int | None = None,
) -> Optional[dict]:
    """DB에서 현재 대화의 active cart를 우선 조회한다."""
    stmt = select(Cart).where(Cart.user_id == user_id, Cart.status == "active")
    if conversation_id is not None:
        stmt = stmt.where(Cart.conversation_id == conversation_id)
    stmt = stmt.order_by(Cart.id.desc())

    result = await db.execute(stmt)
    cart = result.scalars().first()
    if not cart:
        return None
    return _cart_to_dict(cart)


async def get_or_create_active_cart_db(
    db: AsyncSession,
    *,
    user_id: int,
    conversation_id: int | None,
) -> dict:
    """없으면 만들고, 있으면 재사용하는 active cart를 반환한다."""
    existing = await get_active_cart_by_user_id_db(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if existing:
        return existing

    cart = Cart(
        user_id=user_id,
        conversation_id=conversation_id,
        status="active",
    )
    db.add(cart)
    await db.commit()
    await db.refresh(cart)
    return _cart_to_dict(cart)


async def get_cart_items_by_cart_id_db(
    db: AsyncSession,
    cart_id: int,
) -> list[dict]:
    """DB cart_items 목록을 조회한다."""
    result = await db.execute(
        select(CartItem).where(CartItem.cart_id == cart_id).order_by(CartItem.id.asc())
    )
    return [_cart_item_to_dict(item) for item in result.scalars().all()]


async def add_recommendation_item_to_cart_db(
    db: AsyncSession,
    *,
    cart_id: int,
    recommendation_item_id: int,
    quantity: int = 1,
) -> dict:
    """선택된 recommendation_item snapshot을 cart_items에 복사한다."""
    recommendation_item = await db.get(RecommendationItem, recommendation_item_id)
    if not recommendation_item:
        raise ValueError("추천 후보를 찾을 수 없습니다.")
    if recommendation_item.product_id is None:
        raise ValueError("내부 product_id가 없는 추천 후보는 장바구니에 담을 수 없습니다.")
    if not recommendation_item.is_orderable:
        reason = recommendation_item.order_block_reason or "자동 주문이 불가능한 상품입니다."
        raise ValueError(reason)

    result = await db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart_id,
            CartItem.recommendation_item_id == recommendation_item_id,
        )
    )
    existing = result.scalars().first()
    if existing:
        existing.quantity = max(existing.quantity, quantity)
        existing.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(existing)
        return _cart_item_to_dict(existing)

    unit_price = recommendation_item.price_at_recommendation or 0
    item = CartItem(
        cart_id=cart_id,
        product_id=recommendation_item.product_id,
        product_option_id=recommendation_item.product_option_id,
        recommendation_item_id=recommendation_item.id,
        quantity=quantity,
        unit_price_snapshot=unit_price,
        product_name_snapshot=recommendation_item.product_name_snapshot,
        option_snapshot=recommendation_item.option_snapshot,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _cart_item_to_dict(item)

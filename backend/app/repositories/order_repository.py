from typing import Optional, List
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mock_data.orders import MOCK_ORDERS, MOCK_ORDER_ITEMS
from app.models.order import Cart, CartItem, CheckoutSession, Order, OrderItem
from app.models.recommendation import RecommendationItem

def get_order_by_id(order_id: int) -> Optional[dict]:
    return next((o for o in MOCK_ORDERS if o["id"] == order_id), None)

def get_orders_by_user_id(user_id: int) -> List[dict]:
    return [o for o in MOCK_ORDERS if o["user_id"] == user_id]

def get_order_items_by_order_id(order_id: int) -> List[dict]:
    return [i for i in MOCK_ORDER_ITEMS if i["order_id"] == order_id]

def cancel_order(order_id: int) -> Optional[dict]:
    order = get_order_by_id(order_id)
    if not order:
        return None
    order["status"] = "cancelled"
    return order


def _order_to_dict(order: Order) -> dict:
    """ORM Order를 기존 service/mapper가 쓰는 dict 형태로 변환한다."""
    return {
        "id": order.id,
        "user_id": order.user_id,
        "conversation_id": order.conversation_id,
        "cart_id": order.cart_id,
        "checkout_session_id": order.checkout_session_id,
        "recommendation_id": order.recommendation_id,
        "shipping_address_id": order.shipping_address_id,
        "recipient_name_snapshot": order.recipient_name_snapshot,
        "recipient_phone_snapshot": order.recipient_phone_snapshot,
        "shipping_address_snapshot": order.shipping_address_snapshot,
        "delivery_request_snapshot": order.delivery_request_snapshot,
        "platform": order.platform,
        "order_type": order.order_type,
        "status": order.status,
        "total_product_price": order.total_product_price,
        "delivery_fee": order.delivery_fee,
        "total_payment_amount": order.total_payment_amount,
        "confirmed_by_user": order.confirmed_by_user,
        "confirmed_at": order.confirmed_at,
        "ordered_at": order.ordered_at,
        "idempotency_key": order.idempotency_key,
        "failed_reason": order.failed_reason,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def _order_item_to_dict(item: OrderItem) -> dict:
    """ORM OrderItem snapshot을 dict로 변환한다."""
    return {
        "id": item.id,
        "order_id": item.order_id,
        "product_id": item.product_id,
        "product_option_id": item.product_option_id,
        "recommendation_item_id": item.recommendation_item_id,
        "product_name_snapshot": item.product_name_snapshot,
        "option_snapshot": item.option_snapshot,
        "product_url_snapshot": item.product_url_snapshot,
        "selected_options": item.selected_options,
        "unit_price": item.unit_price,
        "total_price": item.total_price,
        "quantity": item.quantity,
        "external_product_order_id": item.external_product_order_id,
        "created_at": item.created_at,
    }


def _checkout_session_to_dict(checkout_session: CheckoutSession) -> dict:
    """ORM CheckoutSession을 dict로 변환한다."""
    return {
        "id": checkout_session.id,
        "user_id": checkout_session.user_id,
        "conversation_id": checkout_session.conversation_id,
        "cart_id": checkout_session.cart_id,
        "delivery_address_snapshot": checkout_session.delivery_address_snapshot,
        "address_confirmed": checkout_session.address_confirmed,
        "total_product_price": checkout_session.total_product_price,
        "delivery_fee": checkout_session.delivery_fee,
        "total_expected_amount": checkout_session.total_expected_amount,
        "status": checkout_session.status,
        "idempotency_key": checkout_session.idempotency_key,
        "created_at": checkout_session.created_at,
        "updated_at": checkout_session.updated_at,
    }


def _address_snapshot(address: dict | None) -> dict:
    """배송지 dict에서 주문 snapshot 컬럼에 넣을 값을 만든다."""
    if not address:
        return {
            "shipping_address_id": None,
            "recipient_name_snapshot": None,
            "recipient_phone_snapshot": None,
            "shipping_address_snapshot": None,
            "delivery_request_snapshot": None,
            "delivery_address_snapshot": None,
            "address_confirmed": False,
        }

    address_line1 = address.get("address_line1") or ""
    address_line2 = address.get("address_line2") or ""
    full_address = f"{address_line1} {address_line2}".strip()
    return {
        "shipping_address_id": address.get("id"),
        "recipient_name_snapshot": address.get("recipient_name"),
        "recipient_phone_snapshot": address.get("recipient_phone"),
        "shipping_address_snapshot": full_address or None,
        "delivery_request_snapshot": address.get("delivery_request"),
        "delivery_address_snapshot": full_address or None,
        "address_confirmed": bool(full_address),
    }


async def get_order_by_id_db(db: AsyncSession, order_id: int) -> Optional[dict]:
    """DB 주문 단건을 조회한다."""
    order = await db.get(Order, order_id)
    if not order:
        return None
    return _order_to_dict(order)


async def get_order_items_by_order_id_db(
    db: AsyncSession,
    order_id: int,
) -> list[dict]:
    """DB 주문 상품 목록을 조회한다."""
    result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id.asc())
    )
    return [_order_item_to_dict(item) for item in result.scalars().all()]


async def update_order_status_db(
    db: AsyncSession,
    order_id: int,
    *,
    status: str,
    failed_reason: str | None = None,
) -> Optional[dict]:
    """주문 상태를 결제 결과에 맞춰 갱신한다."""
    order = await db.get(Order, order_id)
    if not order:
        return None

    order.status = status
    order.failed_reason = failed_reason
    if status == "order_completed":
        order.ordered_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(order)
    return _order_to_dict(order)


async def create_order_from_cart_db(
    db: AsyncSession,
    *,
    cart_id: int,
    user_id: int,
    conversation_id: int | None,
    address: dict | None = None,
    status: str = "payment_pending",
    order_type: str = "agent_order",
) -> dict:
    """
    cart_items snapshot을 기준으로 checkout_session, orders, order_items를 생성한다.

    같은 cart로 이미 생성된 진행 중 주문이 있으면 중복 생성 대신 기존 주문을 반환한다.
    """
    result = await db.execute(
        select(Order).where(
            Order.cart_id == cart_id,
            Order.status.in_(["pending_confirmation", "payment_pending", "order_completed"]),
        ).order_by(Order.id.desc())
    )
    existing_order = result.scalars().first()
    if existing_order:
        checkout_session = await db.get(CheckoutSession, existing_order.checkout_session_id)
        return {
            "checkout_session": (
                _checkout_session_to_dict(checkout_session) if checkout_session else None
            ),
            "order": _order_to_dict(existing_order),
            "order_items": await get_order_items_by_order_id_db(db, existing_order.id),
        }

    cart = await db.get(Cart, cart_id)
    if not cart:
        raise ValueError("장바구니를 찾을 수 없습니다.")

    cart_items_result = await db.execute(
        select(CartItem).where(CartItem.cart_id == cart_id).order_by(CartItem.id.asc())
    )
    cart_items = cart_items_result.scalars().all()
    if not cart_items:
        raise ValueError("주문할 장바구니 상품이 없습니다.")

    total_product_price = sum(
        (item.unit_price_snapshot or 0) * item.quantity for item in cart_items
    )
    delivery_fee = 0
    total_payment_amount = total_product_price + delivery_fee
    snapshot = _address_snapshot(address)
    now = datetime.now(UTC)

    checkout_session = CheckoutSession(
        user_id=user_id,
        conversation_id=conversation_id,
        cart_id=cart_id,
        delivery_address_snapshot=snapshot["delivery_address_snapshot"],
        address_confirmed=snapshot["address_confirmed"],
        total_product_price=total_product_price,
        delivery_fee=delivery_fee,
        total_expected_amount=total_payment_amount,
        status="active",
        idempotency_key=f"checkout:{cart_id}",
    )
    db.add(checkout_session)
    await db.flush()

    first_recommendation_item = None
    if cart_items[0].recommendation_item_id:
        first_recommendation_item = await db.get(
            RecommendationItem,
            cart_items[0].recommendation_item_id,
        )

    order = Order(
        user_id=user_id,
        conversation_id=conversation_id,
        cart_id=cart_id,
        checkout_session_id=checkout_session.id,
        recommendation_id=(
            first_recommendation_item.recommendation_id
            if first_recommendation_item
            else None
        ),
        shipping_address_id=snapshot["shipping_address_id"],
        recipient_name_snapshot=snapshot["recipient_name_snapshot"],
        recipient_phone_snapshot=snapshot["recipient_phone_snapshot"],
        shipping_address_snapshot=snapshot["shipping_address_snapshot"],
        delivery_request_snapshot=snapshot["delivery_request_snapshot"],
        platform=(first_recommendation_item.platform if first_recommendation_item else "unknown"),
        order_type=order_type,
        status=status,
        total_product_price=total_product_price,
        delivery_fee=delivery_fee,
        total_payment_amount=total_payment_amount,
        confirmed_by_user=True,
        confirmed_at=now,
        ordered_at=None,
        idempotency_key=f"order:{cart_id}",
    )
    db.add(order)
    await db.flush()

    for cart_item in cart_items:
        recommendation_item = (
            await db.get(RecommendationItem, cart_item.recommendation_item_id)
            if cart_item.recommendation_item_id
            else None
        )
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=cart_item.product_id,
                product_option_id=cart_item.product_option_id,
                recommendation_item_id=cart_item.recommendation_item_id,
                product_name_snapshot=cart_item.product_name_snapshot,
                option_snapshot=cart_item.option_snapshot,
                product_url_snapshot=(
                    recommendation_item.product_url_snapshot if recommendation_item else None
                ),
                selected_options=None,
                unit_price=cart_item.unit_price_snapshot,
                total_price=cart_item.unit_price_snapshot * cart_item.quantity,
                quantity=cart_item.quantity,
            )
        )

    cart.status = "checked_out"
    await db.commit()
    await db.refresh(checkout_session)
    await db.refresh(order)

    return {
        "checkout_session": _checkout_session_to_dict(checkout_session),
        "order": _order_to_dict(order),
        "order_items": await get_order_items_by_order_id_db(db, order.id),
    }

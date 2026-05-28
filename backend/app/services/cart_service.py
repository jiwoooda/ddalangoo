from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import cart_repository, user_repository
from app.schemas.cart import CartResponse, CartItemResponse


def _to_cart_item_response(item: dict) -> CartItemResponse:
    """DB cart item snapshot을 기존 CartItemResponse DTO로 변환한다."""
    unit_price = item.get("unit_price_snapshot", 0)
    quantity = item.get("quantity", 1)
    return CartItemResponse(
        cartItemId=item["id"],
        productId=item["product_id"],
        productOptionId=item.get("product_option_id"),
        productName=item["product_name_snapshot"],
        optionText=item.get("option_snapshot"),
        unitPrice=unit_price,
        quantity=quantity,
        totalPrice=unit_price * quantity,
    )


async def get_cart_db(db: AsyncSession, user_id: int) -> CartResponse:
    """사용자의 active cart를 DB에서 조회한다."""
    if not await user_repository.get_user_by_id_db(db, user_id):
        raise HTTPException(
            status_code=404,
            detail={
                "category": "USER_ERROR",
                "code": "USER_NOT_FOUND",
                "message": "사용자를 찾을 수 없습니다.",
            },
        )

    cart = await cart_repository.get_active_cart_by_user_id_db(db, user_id=user_id)
    if not cart:
        return CartResponse(cartId=None, userId=user_id, status="active", items=[])

    items = await cart_repository.get_cart_items_by_cart_id_db(db, cart["id"])
    return CartResponse(
        cartId=cart["id"],
        userId=user_id,
        status=cart.get("status", "active"),
        items=[_to_cart_item_response(item) for item in items],
    )


async def add_cart_item_db(
    db: AsyncSession,
    cart_id: int,
    *,
    product_id: int,
    product_option_id: int | None,
    quantity: int,
) -> CartItemResponse:
    """일반 cart API에서 상품을 DB cart_items에 추가한다."""
    try:
        item = await cart_repository.add_product_to_cart_db(
            db,
            cart_id=cart_id,
            product_id=product_id,
            product_option_id=product_option_id,
            quantity=quantity,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "category": "CART_ERROR",
                "code": "CART_ITEM_CREATE_FAILED",
                "message": str(error),
            },
        ) from error
    return _to_cart_item_response(item)


async def delete_cart_item_db(db: AsyncSession, cart_id: int, cart_item_id: int) -> dict:
    """DB cart item을 삭제한다."""
    if not await cart_repository.delete_cart_item_db(db, cart_id, cart_item_id):
        raise HTTPException(status_code=404, detail="Cart item not found")
    return {"message": "장바구니 상품이 삭제되었습니다."}

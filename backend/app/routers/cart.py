from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.cart import CartResponse, CartItemResponse
from app.services import cart_service
from pydantic import BaseModel
from typing import Optional

class CartItemAddRequest(BaseModel):
    productId: int
    productOptionId: Optional[int] = None
    quantity: int = 1

router = APIRouter(tags=["Cart"])

@router.get("/users/{userId}/cart", response_model=CartResponse)
async def get_cart(userId: int, db: AsyncSession = Depends(get_db)):
    return await cart_service.get_cart_db(db, userId)

@router.post("/carts/{cartId}/items")
async def add_cart_item(cartId: int, req: CartItemAddRequest, db: AsyncSession = Depends(get_db)):
    return await cart_service.add_cart_item_db(
        db,
        cartId,
        product_id=req.productId,
        product_option_id=req.productOptionId,
        quantity=req.quantity,
    )

@router.delete("/carts/{cartId}/items/{cartItemId}")
async def delete_cart_item(cartId: int, cartItemId: int, db: AsyncSession = Depends(get_db)):
    return await cart_service.delete_cart_item_db(db, cartId, cartItemId)

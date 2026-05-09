from fastapi import APIRouter, HTTPException
from app.repositories import cart_repository, user_repository
from app.mock_data.products import MOCK_PRODUCTS
from app.schemas.cart import CartResponse, CartItemResponse
from pydantic import BaseModel
from typing import Optional

class CartItemAddRequest(BaseModel):
    productId: int
    productOptionId: Optional[int] = None
    quantity: int = 1

router = APIRouter(tags=["Cart"])

@router.get("/users/{userId}/cart", response_model=CartResponse)
def get_cart(userId: int):
    if not user_repository.get_user_by_id(userId):
        raise HTTPException(status_code=404, detail={"category": "USER_ERROR", "code": "USER_NOT_FOUND", "message": "사용자를 찾을 수 없습니다."})
    cart = cart_repository.get_cart_by_user_id(userId)
    if not cart:
        return {"cartId": None, "userId": userId, "status": "active", "items": []}
    items = cart_repository.get_cart_items_by_cart_id(cart["id"])
    return {"cartId": cart["id"], "userId": userId, "status": cart.get("status", "active"),
            "items": [{"cartItemId": i["id"], "productId": i["product_id"], "productOptionId": i.get("product_option_id"),
                       "productName": i["product_name"], "optionText": i.get("option_text"),
                       "unitPrice": i.get("unit_price", 0), "quantity": i["quantity"],
                       "totalPrice": i.get("total_price", 0)} for i in items]}

@router.post("/carts/{cartId}/items")
def add_cart_item(cartId: int, req: CartItemAddRequest):
    product = next((p for p in MOCK_PRODUCTS if p["id"] == req.productId), None)
    if not product:
        raise HTTPException(status_code=404, detail={"category": "PRODUCT_ERROR", "code": "PRODUCT_NOT_FOUND", "message": "상품을 찾을 수 없습니다."})
    data = {"product_id": req.productId, "product_option_id": req.productOptionId,
            "product_name": product["name"], "option_text": None,
            "unit_price": product["current_price"], "quantity": req.quantity,
            "total_price": product["current_price"] * req.quantity}
    item = cart_repository.add_cart_item(cartId, data)
    return {"cartItemId": item["id"], "productId": item["product_id"], "productOptionId": item.get("product_option_id"),
            "productName": item["product_name"], "optionText": item.get("option_text"),
            "unitPrice": item.get("unit_price", 0), "quantity": item["quantity"], "totalPrice": item.get("total_price", 0)}

@router.delete("/carts/{cartId}/items/{cartItemId}")
def delete_cart_item(cartId: int, cartItemId: int):
    if not cart_repository.delete_cart_item(cartId, cartItemId):
        raise HTTPException(status_code=404, detail="Cart item not found")
    return {"message": "장바구니 상품이 삭제되었습니다."}

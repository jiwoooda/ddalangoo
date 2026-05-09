from app.mock_data.carts import MOCK_CARTS, MOCK_CART_ITEMS
from typing import Optional, List

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

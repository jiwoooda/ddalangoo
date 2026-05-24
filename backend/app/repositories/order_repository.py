from app.mock_data.orders import MOCK_ORDERS, MOCK_ORDER_ITEMS
from typing import Optional, List

def get_order_by_id(order_id: int) -> Optional[dict]:
    return next((o for o in MOCK_ORDERS if o["id"] == order_id), None)

def get_orders_by_user_id(user_id: int) -> List[dict]:
    return [o for o in MOCK_ORDERS if o["user_id"] == user_id]

def get_order_by_conversation_id(conversation_id: int) -> Optional[dict]:
    return next((o for o in MOCK_ORDERS if o.get("conversation_id") == conversation_id), None)

def get_order_items_by_order_id(order_id: int) -> List[dict]:
    return [i for i in MOCK_ORDER_ITEMS if i["order_id"] == order_id]

def cancel_order(order_id: int) -> Optional[dict]:
    order = get_order_by_id(order_id)
    if not order:
        return None
    order["status"] = "cancelled"
    return order

from app.mock_data.payments import MOCK_PAYMENTS
from typing import Optional

def get_payment_by_id(payment_id: int) -> Optional[dict]:
    return next((p for p in MOCK_PAYMENTS if p["id"] == payment_id), None)

def get_payment_by_order_id(order_id: int) -> Optional[dict]:
    return next((p for p in MOCK_PAYMENTS if p["order_id"] == order_id), None)

def update_payment(payment_id: int, data: dict) -> Optional[dict]:
    payment = get_payment_by_id(payment_id)
    if not payment:
        return None
    payment.update(data)
    return payment

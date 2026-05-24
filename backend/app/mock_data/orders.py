MOCK_CHECKOUT_SESSIONS = [
    {"id": 1, "user_id": 1, "conversation_id": 42, "status": "pending"},
]

MOCK_ORDERS = [
    {"id": 77, "user_id": 1, "conversation_id": 42, "status": "order_completed", "platform": "naver", "total_product_price": 12000, "delivery_fee": 0, "total_payment_amount": 12000, "confirmed_at": "2026-04-30T18:29:50", "ordered_at": "2026-04-30T18:30:00", "shipping_recipient_name": "김영희", "shipping_recipient_phone": "010-1234-5678", "shipping_address": "서울시 강남구 테헤란로 1길 10 101호", "delivery_request": "문 앞에 놓아주세요"},
]

MOCK_ORDER_ITEMS = [
    {"id": 1, "order_id": 77, "product_id": 1, "product_option_id": 1, "product_name": "설향 딸기 500g", "option_text": "500g", "selected_options": {"용량": "500g"}, "product_url": "https://example.com/product/1", "unit_price": 12000, "quantity": 1, "total_price": 12000},
]

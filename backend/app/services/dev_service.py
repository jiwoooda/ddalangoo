from app.mock_data.products import MOCK_PRODUCTS
from app.mock_data.purchase_histories import MOCK_PURCHASE_HISTORIES

def get_sample_products() -> dict:
    return {"message": "샘플 상품 데이터가 생성되었습니다.", "createdCount": len(MOCK_PRODUCTS)}

def get_sample_purchase_histories(user_id: int = 1) -> dict:
    histories = [h for h in MOCK_PURCHASE_HISTORIES if h["user_id"] == user_id]
    return {"message": "샘플 구매 이력이 생성되었습니다.", "createdCount": len(histories)}

from app.mock_data.products import MOCK_PRODUCTS
from app.repositories import purchase_history_repository

def get_sample_products() -> dict:
    return {"message": "샘플 상품 데이터가 생성되었습니다.", "createdCount": len(MOCK_PRODUCTS)}

def get_sample_purchase_histories(user_id: int | None = None) -> dict:
    histories = purchase_history_repository.get_histories_by_user_id(user_id)
    return {"message": "샘플 구매 이력이 생성되었습니다.", "createdCount": len(histories)}

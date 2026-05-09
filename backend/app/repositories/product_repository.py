from app.mock_data.products import MOCK_PRODUCTS, MOCK_PRODUCT_OPTIONS, MOCK_NAVER_PRODUCT_MAPPINGS
from typing import Optional, List

def get_all_products() -> List[dict]:
    return MOCK_PRODUCTS

def get_product_by_id(product_id: int) -> Optional[dict]:
    return next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)

def get_options_by_product_id(product_id: int) -> List[dict]:
    return [o for o in MOCK_PRODUCT_OPTIONS if o["product_id"] == product_id]

def get_naver_mappings_by_product_id(product_id: int) -> List[dict]:
    return [m for m in MOCK_NAVER_PRODUCT_MAPPINGS if m["product_id"] == product_id]

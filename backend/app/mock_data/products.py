MOCK_PRODUCTS = [
    {"id": 1, "name": "설향 딸기 500g", "brand": "설향", "category": "fruit", "sub_category": "strawberry", "current_price": 12000, "rating": 4.8, "review_count": 1200, "image_url": "https://example.com/strawberry.jpg", "description": "국내산 설향 딸기 500g", "is_available": True},
    {"id": 2, "name": "국산 딸기 750g", "brand": "농협", "category": "fruit", "sub_category": "strawberry", "current_price": 15000, "rating": 4.5, "review_count": 800, "image_url": None, "description": None, "is_available": True},
    {"id": 3, "name": "못난이 딸기 1kg", "brand": "못난이농장", "category": "fruit", "sub_category": "strawberry", "current_price": 10000, "rating": 4.2, "review_count": 300, "image_url": None, "description": None, "is_available": False},
    {"id": 4, "name": "국산 참기름 300ml", "brand": "CJ", "category": "condiment", "sub_category": "sesame_oil", "current_price": 8000, "rating": 4.7, "review_count": 500, "image_url": None, "description": None, "is_available": True},
    {"id": 5, "name": "들기름 300ml", "brand": "오뚜기", "category": "condiment", "sub_category": "perilla_oil", "current_price": 9000, "rating": 4.6, "review_count": 400, "image_url": None, "description": None, "is_available": True},
    {"id": 6, "name": "검은콩 두유 190ml 24팩", "brand": "정식품", "category": "beverage", "sub_category": "soy_milk", "current_price": 18000, "rating": 4.8, "review_count": 2000, "image_url": None, "description": None, "is_available": True},
    {"id": 7, "name": "무가당 두유 200ml 24팩", "brand": "삼육", "category": "beverage", "sub_category": "soy_milk", "current_price": 16000, "rating": 4.5, "review_count": 1500, "image_url": None, "description": None, "is_available": True},
]

MOCK_PRODUCT_OPTIONS = [
    {"id": 1, "product_id": 1, "option_name": "용량", "option_value": "500g", "volume": "500g", "additional_price": 0, "stock_quantity": 50, "is_available": True},
    {"id": 2, "product_id": 6, "option_name": "용량", "option_value": "190ml 24팩", "volume": "190ml", "additional_price": 0, "stock_quantity": 100, "is_available": True},
    {"id": 3, "product_id": 6, "option_name": "용량", "option_value": "190ml 48팩", "volume": "190ml", "additional_price": 16000, "stock_quantity": 30, "is_available": True},
]

MOCK_NAVER_PRODUCT_MAPPINGS = [
    {"product_id": 1, "naver_product_id": "naver_001", "mall_name": "네이버쇼핑", "product_url": "https://example.com/product/1", "external_option_id": "naver-option-001"},
    {"product_id": 4, "naver_product_id": "naver_004", "mall_name": "네이버쇼핑", "product_url": "https://example.com/product/4", "external_option_id": None},
    {"product_id": 6, "naver_product_id": "naver_006", "mall_name": "네이버쇼핑", "product_url": "https://example.com/product/6", "external_option_id": "naver-option-006"},
]

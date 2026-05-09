from app.repositories import product_repository
from app.schemas.product import ProductSummary, ProductListResponse, ProductDetailResponse, ProductOptionDetail, ExternalMapping, ProductOptionsResponse
from fastapi import HTTPException
from typing import Optional

def _opt_to_detail(o: dict) -> ProductOptionDetail:
    return ProductOptionDetail(
        productOptionId=o["id"], optionName=o["option_name"], optionValue=o["option_value"],
        volume=o.get("volume"), additionalPrice=o.get("additional_price", 0),
        stockQuantity=o.get("stock_quantity"), isAvailable=o.get("is_available", True)
    )

def get_all_products(keyword: Optional[str] = None, category: Optional[str] = None, limit: Optional[int] = None) -> ProductListResponse:
    products = product_repository.get_all_products()
    if keyword:
        products = [p for p in products if keyword in p["name"]]
    if category:
        products = [p for p in products if p.get("category") == category]
    if limit:
        products = products[:limit]
    return ProductListResponse(products=[
        ProductSummary(productId=p["id"], name=p["name"], brand=p.get("brand"),
                       category=p.get("category"), subCategory=p.get("sub_category"),
                       currentPrice=p["current_price"], rating=p.get("rating"),
                       reviewCount=p.get("review_count"), imageUrl=p.get("image_url"),
                       isAvailable=p.get("is_available", True))
        for p in products
    ])

def get_product(product_id: int) -> ProductDetailResponse:
    p = product_repository.get_product_by_id(product_id)
    if not p:
        raise HTTPException(status_code=404, detail={"category": "PRODUCT_ERROR", "code": "PRODUCT_NOT_FOUND", "message": "상품을 찾을 수 없습니다."})
    options = [_opt_to_detail(o) for o in product_repository.get_options_by_product_id(product_id)]
    mappings = product_repository.get_naver_mappings_by_product_id(product_id)
    ext_mappings = [ExternalMapping(platform="naver", mallName=m.get("mall_name"),
                                     productUrl=m.get("product_url"), externalProductId=m.get("naver_product_id"),
                                     externalOptionId=m.get("external_option_id")) for m in mappings]
    return ProductDetailResponse(
        productId=p["id"], name=p["name"], brand=p.get("brand"), category=p.get("category"),
        subCategory=p.get("sub_category"), description=p.get("description"), imageUrl=p.get("image_url"),
        currentPrice=p["current_price"], rating=p.get("rating"), reviewCount=p.get("review_count"),
        isAvailable=p.get("is_available", True), options=options, externalMappings=ext_mappings
    )

def get_product_options(product_id: int) -> ProductOptionsResponse:
    if not product_repository.get_product_by_id(product_id):
        raise HTTPException(status_code=404, detail={"category": "PRODUCT_ERROR", "code": "PRODUCT_NOT_FOUND", "message": "상품을 찾을 수 없습니다."})
    options = [_opt_to_detail(o) for o in product_repository.get_options_by_product_id(product_id)]
    return ProductOptionsResponse(productId=product_id, options=options)

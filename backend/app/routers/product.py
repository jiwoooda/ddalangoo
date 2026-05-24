from fastapi import APIRouter, Query
from app.schemas.product import ProductListResponse, ProductDetailResponse, ProductOptionsResponse
from app.services import product_service
from typing import Optional

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("", response_model=ProductListResponse)
def get_products(keyword: Optional[str] = Query(None), category: Optional[str] = Query(None), limit: Optional[int] = Query(None)):
    return product_service.get_all_products(keyword=keyword, category=category, limit=limit)

@router.get("/{productId}", response_model=ProductDetailResponse)
def get_product(productId: int):
    return product_service.get_product(productId)

@router.get("/{productId}/options", response_model=ProductOptionsResponse)
def get_product_options(productId: int):
    return product_service.get_product_options(productId)

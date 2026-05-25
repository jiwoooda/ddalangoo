from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.product import ProductListResponse, ProductDetailResponse, ProductOptionsResponse
from app.services import product_service
from typing import Optional

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("", response_model=ProductListResponse)
async def get_products(
    keyword: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await product_service.get_all_products_db(db, keyword=keyword, category=category, limit=limit)

@router.get("/{productId}", response_model=ProductDetailResponse)
async def get_product(productId: int, db: AsyncSession = Depends(get_db)):
    return await product_service.get_product_db(db, productId)

@router.get("/{productId}/options", response_model=ProductOptionsResponse)
def get_product_options(productId: int):
    return product_service.get_product_options(productId)

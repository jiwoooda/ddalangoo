from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.purchase_history import PurchaseHistoryListResponse, PurchaseHistoryDetailResponse
from app.services import purchase_history_service
from typing import Optional

router = APIRouter(tags=["Purchase Histories"])

@router.get("/users/{userId}/purchase-histories", response_model=PurchaseHistoryListResponse)
async def get_user_histories(
    userId: int,
    keyword: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await purchase_history_service.get_histories_db(db, userId, keyword=keyword, category=category, limit=limit)

@router.get("/purchase-histories/{purchaseHistoryId}", response_model=PurchaseHistoryDetailResponse)
async def get_history(purchaseHistoryId: int, db: AsyncSession = Depends(get_db)):
    return await purchase_history_service.get_history_db(db, purchaseHistoryId)

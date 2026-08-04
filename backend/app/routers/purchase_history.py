from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.purchase_history import (
    AccessibilityPurchaseHistoryImportRequest,
    AccessibilityPurchaseHistoryImportResponse,
    PurchaseHistoryListResponse,
    PurchaseHistoryDetailResponse,
)
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


@router.post(
    "/users/{userId}/purchase-histories/accessibility-import",
    response_model=AccessibilityPurchaseHistoryImportResponse,
)
async def import_accessibility_histories(
    userId: int,
    request: AccessibilityPurchaseHistoryImportRequest,
    db: AsyncSession = Depends(get_db),
):
    return await purchase_history_service.create_histories_from_accessibility_db(
        db,
        user_id=userId,
        items=request.items,
    )

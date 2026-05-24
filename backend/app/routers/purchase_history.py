from fastapi import APIRouter, Query
from app.schemas.purchase_history import PurchaseHistoryListResponse, PurchaseHistoryDetailResponse
from app.services import purchase_history_service
from typing import Optional

router = APIRouter(tags=["Purchase Histories"])

@router.get("/users/{userId}/purchase-histories", response_model=PurchaseHistoryListResponse)
def get_user_histories(userId: int, keyword: Optional[str] = Query(None), category: Optional[str] = Query(None), limit: Optional[int] = Query(None)):
    return purchase_history_service.get_histories(userId, keyword=keyword, category=category, limit=limit)

@router.get("/purchase-histories/{purchaseHistoryId}", response_model=PurchaseHistoryDetailResponse)
def get_history(purchaseHistoryId: int):
    return purchase_history_service.get_history(purchaseHistoryId)

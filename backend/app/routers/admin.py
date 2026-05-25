from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import admin_service
from app.schemas.admin import ExternalApiLogResponse
from typing import Optional

router = APIRouter(prefix="/admin", tags=["Admin"])

@router.get("/external-api-logs", response_model=ExternalApiLogResponse)
async def get_external_api_logs(
    provider: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    conversationId: Optional[int] = Query(None),
    limit: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await admin_service.get_external_api_logs_db(
        db,
        provider=provider,
        success=success,
        conversation_id=conversationId,
        limit=limit,
    )

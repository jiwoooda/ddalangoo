from fastapi import APIRouter, Query
from app.services import admin_service
from app.schemas.admin import ExternalApiLogResponse
from typing import Optional

router = APIRouter(prefix="/admin", tags=["Admin"])

@router.get("/external-api-logs", response_model=ExternalApiLogResponse)
def get_external_api_logs(provider: Optional[str] = Query(None), success: Optional[bool] = Query(None),
                          conversationId: Optional[int] = Query(None), limit: Optional[int] = Query(None)):
    return admin_service.get_external_api_logs(provider=provider, success=success, conversation_id=conversationId, limit=limit)

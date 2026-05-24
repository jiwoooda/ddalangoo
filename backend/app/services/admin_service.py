from app.repositories import external_api_log_repository
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

def get_external_api_logs(provider: Optional[str] = None, success: Optional[bool] = None,
                           conversation_id: Optional[int] = None, limit: Optional[int] = None) -> dict:
    logs = external_api_log_repository.get_all_logs()
    if provider:
        logs = [l for l in logs if l.get("provider") == provider]
    if success is not None:
        logs = [l for l in logs if l.get("success") == success]
    if conversation_id is not None:
        logs = [l for l in logs if l.get("conversation_id") == conversation_id]
    if limit:
        logs = logs[:limit]
    return {"logs": [{"logId": l["id"], "userId": l.get("user_id"), "conversationId": l.get("conversation_id"),
                      "provider": l.get("provider"), "apiName": l.get("api_name"), "statusCode": l.get("status_code"),
                      "success": l.get("success"), "requestSummary": l.get("request_summary"),
                      "responseSummary": l.get("response_summary"), "errorMessage": l.get("error_message"),
                      "createdAt": l.get("created_at")} for l in logs]}


async def get_external_api_logs_db(
    db: AsyncSession,
    provider: Optional[str] = None,
    success: Optional[bool] = None,
    conversation_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> dict:
    """DB에 저장된 외부 API/tool 호출 로그를 조회한다."""
    logs = await external_api_log_repository.get_all_logs_db(
        db,
        provider=provider,
        success=success,
        conversation_id=conversation_id,
        limit=limit,
    )
    return {"logs": [{"logId": l["id"], "userId": l.get("user_id"), "conversationId": l.get("conversation_id"),
                      "provider": l.get("provider"), "apiName": l.get("api_name"), "statusCode": l.get("status_code"),
                      "success": l.get("success"), "requestSummary": l.get("request_summary"),
                      "responseSummary": l.get("response_summary"), "errorMessage": l.get("error_message"),
                      "createdAt": l.get("created_at")} for l in logs]}

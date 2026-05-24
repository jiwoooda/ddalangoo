from app.mock_data.external_api_logs import MOCK_EXTERNAL_API_LOGS
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log import ExternalApiLog

def get_all_logs() -> List[dict]:
    return MOCK_EXTERNAL_API_LOGS


def _external_api_log_to_dict(log: ExternalApiLog) -> dict:
    """ORM ExternalApiLog를 admin 응답용 dict로 변환한다."""
    return {
        "id": log.id,
        "user_id": log.user_id,
        "conversation_id": log.conversation_id,
        "provider": log.provider,
        "api_name": log.api_name,
        "request_summary": log.request_summary,
        "response_summary": log.response_summary,
        "status_code": log.status_code,
        "success": log.success,
        "error_message": log.error_message,
        "latency_ms": log.latency_ms,
        "created_at": log.created_at,
    }


async def create_external_api_log_db(db: AsyncSession, data: dict) -> dict:
    """외부 API/tool 호출 결과 요약을 DB에 저장한다."""
    log = ExternalApiLog(
        user_id=data.get("user_id"),
        conversation_id=data.get("conversation_id"),
        provider=data["provider"],
        api_name=data["api_name"],
        request_summary=data.get("request_summary"),
        response_summary=data.get("response_summary"),
        status_code=data.get("status_code"),
        success=data["success"],
        error_message=data.get("error_message"),
        latency_ms=data.get("latency_ms"),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _external_api_log_to_dict(log)


async def get_all_logs_db(
    db: AsyncSession,
    provider: str | None = None,
    success: bool | None = None,
    conversation_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    """DB의 외부 API 로그를 필터링 조회한다."""
    stmt = select(ExternalApiLog).order_by(ExternalApiLog.id.desc())
    if provider:
        stmt = stmt.where(ExternalApiLog.provider == provider)
    if success is not None:
        stmt = stmt.where(ExternalApiLog.success == success)
    if conversation_id is not None:
        stmt = stmt.where(ExternalApiLog.conversation_id == conversation_id)
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return [_external_api_log_to_dict(log) for log in result.scalars().all()]

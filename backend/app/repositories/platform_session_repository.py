"""사용자별 플랫폼 세션(컬리 등) 조회/저장 repository."""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_session import UserPlatformSession


async def get_active_session_db(
    db: AsyncSession,
    user_id: int,
    platform: str = "kurly",
    account_label: str = "default",
    session_type: str = "playwright_storage_state",
) -> UserPlatformSession | None:
    """활성 세션을 조회한다. 없으면 None 반환."""
    result = await db.execute(
        select(UserPlatformSession).where(
            UserPlatformSession.user_id == user_id,
            UserPlatformSession.platform == platform,
            UserPlatformSession.account_label == account_label,
            UserPlatformSession.session_type == session_type,
            UserPlatformSession.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def upsert_session_file_path_db(
    db: AsyncSession,
    user_id: int,
    session_file_path: str,
    platform: str = "kurly",
    account_label: str = "default",
    session_type: str = "playwright_storage_state",
) -> UserPlatformSession:
    """세션 파일 경로를 upsert 한다.
    이미 레코드가 있으면 session_file_path + last_used_at 을 갱신하고,
    없으면 새로 생성한다.
    """
    existing = await get_active_session_db(
        db, user_id, platform, account_label, session_type
    )
    now = datetime.now(timezone.utc)
    if existing:
        existing.session_file_path = session_file_path
        existing.last_used_at = now
        await db.flush()
        return existing

    session = UserPlatformSession(
        user_id=user_id,
        platform=platform,
        account_label=account_label,
        session_type=session_type,
        session_file_path=session_file_path,
        is_active=True,
        is_default=True,
        last_used_at=now,
    )
    db.add(session)
    await db.flush()
    return session


async def update_last_used_db(
    db: AsyncSession,
    user_id: int,
    platform: str = "kurly",
) -> None:
    """마지막 사용 시각을 현재로 갱신한다."""
    await db.execute(
        update(UserPlatformSession)
        .where(
            UserPlatformSession.user_id == user_id,
            UserPlatformSession.platform == platform,
            UserPlatformSession.is_active.is_(True),
        )
        .values(last_used_at=datetime.now(timezone.utc))
    )

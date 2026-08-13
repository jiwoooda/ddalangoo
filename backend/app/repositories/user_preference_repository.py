"""
UserPreference 캐시 레포지토리.

운영에서는 user_preference_cache DB 테이블을 사용한다.
이번 MVP에서는 app/mock_data/user_preferences.json fallback을 사용하지 않는다.
"""
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Optional


logger = logging.getLogger(__name__)


_GENERAL_TTL_HOURS = 24
_KEYWORD_TTL_HOURS = 24
_SessionLocal = None


def _database_url() -> str | None:
    """동기 SQLAlchemy engine이 사용할 DB URL을 만든다."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _session_local():
    """기존 동기 함수 시그니처를 유지하기 위한 lazy sync session factory다."""
    global _SessionLocal
    database_url = _database_url()
    if not database_url:
        return None
    if _SessionLocal is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine(database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


def _is_fresh(entry: dict, ttl_hours: int) -> bool:
    try:
        computed_at = datetime.fromisoformat(str(entry["computed_at"]))
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - computed_at <= timedelta(hours=ttl_hours)
    except Exception:
        return False


def _keywords_key(keywords: list[str]) -> str:
    """같은 키워드 조합이 같은 캐시 키를 갖도록 정렬한다."""
    return "_".join(sorted(str(keyword) for keyword in keywords if keyword))


def _entry_from_row(row: Any) -> dict[str, Any]:
    preference_data = dict(row.preference_data or {})
    return {
        **preference_data,
        "computed_at": row.computed_at.isoformat(),
    }


def _get_cache_row(
    user_id: int,
    *,
    preference_type: str,
    keywords_key: str = "",
):
    session_factory = _session_local()
    if session_factory is None:
        return None

    from sqlalchemy import select
    from app.models.user_preference import UserPreferenceCache

    with session_factory() as session:
        stmt = select(UserPreferenceCache).where(
            UserPreferenceCache.user_id == user_id,
            UserPreferenceCache.preference_type == preference_type,
            UserPreferenceCache.keywords_key == keywords_key,
        )
        return session.execute(stmt).scalar_one_or_none()


def _save_cache_row(
    user_id: int,
    *,
    preference_type: str,
    keywords_key: str = "",
    preference_data: dict[str, Any],
) -> None:
    session_factory = _session_local()
    if session_factory is None:
        return

    from sqlalchemy import select
    from app.models.user_preference import UserPreferenceCache

    now = datetime.now(UTC)
    with session_factory() as session:
        stmt = select(UserPreferenceCache).where(
            UserPreferenceCache.user_id == user_id,
            UserPreferenceCache.preference_type == preference_type,
            UserPreferenceCache.keywords_key == keywords_key,
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row:
            row.preference_data = preference_data
            row.computed_at = now
        else:
            row = UserPreferenceCache(
                user_id=user_id,
                preference_type=preference_type,
                keywords_key=keywords_key,
                preference_data=preference_data,
                computed_at=now,
            )
            session.add(row)
        session.commit()


def _delete_cache_rows(user_id: int, *, preference_type: str | None = None) -> None:
    session_factory = _session_local()
    if session_factory is None:
        return

    from sqlalchemy import delete
    from app.models.user_preference import UserPreferenceCache

    with session_factory() as session:
        stmt = delete(UserPreferenceCache).where(UserPreferenceCache.user_id == user_id)
        if preference_type:
            stmt = stmt.where(UserPreferenceCache.preference_type == preference_type)
        session.execute(stmt)
        session.commit()


def _can_try_database() -> bool:
    """DATABASE_URL이 있으면 우선 DB 캐시를 시도한다."""
    return bool(_database_url())


def get_general_preference(user_id: int) -> Optional[dict[str, Any]]:
    """일반 선호도 캐시를 조회한다. TTL 초과 시 None을 반환한다."""
    if not _can_try_database():
        return None
    try:
        row = _get_cache_row(user_id, preference_type="general")
    except Exception:
        return None
    if not row:
        return None
    entry = _entry_from_row(row)
    return entry if _is_fresh(entry, _GENERAL_TTL_HOURS) else None


def save_general_preference(user_id: int, preference: dict[str, Any]) -> None:
    """일반 선호도를 캐시에 저장한다."""
    if not _can_try_database():
        return
    try:
        _save_cache_row(
            user_id,
            preference_type="general",
            preference_data=dict(preference),
        )
    except Exception:
        return


def get_profile(user_id: int) -> Optional[dict[str, Any]]:
    """장기 프로필(스몰톡 온보딩에서 모은 선호도/알레르기/호칭 등)을 조회한다.

    general/keyword 캐시와 preference_type만 다를 뿐 같은 테이블을 쓰지만,
    이건 TTL로 만료시키면 안 되는 영속적 사실이라 _is_fresh 체크를 하지
    않는다(smalltalk_agent.py의 db_client.get_profile이 이 함수를 호출한다).
    """
    if not _can_try_database():
        return None
    try:
        row = _get_cache_row(user_id, preference_type="profile")
    except Exception:
        return None
    if not row:
        return None
    return _entry_from_row(row)


def save_profile(user_id: int, profile: dict[str, Any]) -> None:
    """장기 프로필을 저장한다(TTL 없음, get_profile과 동일한 preference_type)."""
    if not _can_try_database():
        return
    try:
        _save_cache_row(
            user_id,
            preference_type="profile",
            preference_data=dict(profile),
        )
    except Exception:
        return


def get_keyword_preference(user_id: int, keywords: list[str]) -> Optional[list]:
    """키워드별 선호도 캐시를 조회한다. TTL 초과 시 None을 반환한다."""
    if not keywords:
        return None

    if not _can_try_database():
        return None
    try:
        row = _get_cache_row(
            user_id,
            preference_type="keyword",
            keywords_key=_keywords_key(keywords),
        )
    except Exception:
        return None
    if not row:
        return None
    entry = _entry_from_row(row)
    if not _is_fresh(entry, _KEYWORD_TTL_HOURS):
        return None
    return entry.get("keyword_history")


def save_keyword_preference(user_id: int, keywords: list[str], keyword_history: list) -> None:
    """키워드별 선호도 캐시를 저장한다."""
    if not keywords:
        return

    if not _can_try_database():
        return
    try:
        _save_cache_row(
            user_id,
            preference_type="keyword",
            keywords_key=_keywords_key(keywords),
            preference_data={"keyword_history": keyword_history},
        )
    except Exception:
        return


def invalidate_all_preferences(user_id: int) -> None:
    """구매 완료 후 해당 유저의 모든 선호도 캐시를 무효화한다."""
    if not _can_try_database():
        return
    try:
        _delete_cache_rows(user_id)
    except Exception:
        return


def invalidate_purchase_derived_preferences(user_id: int) -> None:
    """구매내역에서 계산한 캐시만 삭제하고 영구 profile은 보존한다."""
    if not _can_try_database():
        return
    try:
        _delete_cache_rows(user_id, preference_type="general")
        _delete_cache_rows(user_id, preference_type="keyword")
    except Exception:
        logger.exception(
            "Failed to invalidate purchase-derived preferences for user_id=%s", user_id
        )
        raise


def invalidate_general_preference(user_id: int) -> None:
    """일반 선호도 캐시만 무효화한다."""
    if not _can_try_database():
        return
    try:
        _delete_cache_rows(user_id, preference_type="general")
    except Exception:
        return

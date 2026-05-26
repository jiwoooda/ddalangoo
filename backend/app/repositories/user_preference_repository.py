"""
UserPreference 캐시 레포지토리.

운영에서는 user_preference_cache DB 테이블을 사용한다.
DATABASE_URL이 없거나 로컬 DB가 아직 migration 전이면 기존 JSON 캐시로 fallback한다.
"""
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Optional


_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_data", "user_preferences.json")
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


def _load_json() -> dict:
    if not os.path.exists(_JSON_PATH):
        return {}
    try:
        with open(_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(data: dict) -> None:
    try:
        with open(_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def _is_fresh(entry: dict, ttl_hours: int) -> bool:
    try:
        computed_at = datetime.fromisoformat(str(entry["computed_at"]))
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - computed_at <= timedelta(hours=ttl_hours)
    except Exception:
        return False


def _general_json_key(user_id: int) -> str:
    return f"{user_id}:general"


def _keywords_key(keywords: list[str]) -> str:
    """같은 키워드 조합이 같은 캐시 키를 갖도록 정렬한다."""
    return "_".join(sorted(str(keyword) for keyword in keywords if keyword))


def _keyword_json_key(user_id: int, keywords: list[str]) -> str:
    return f"{user_id}:kw_{_keywords_key(keywords)}"


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
    if _can_try_database():
        try:
            row = _get_cache_row(user_id, preference_type="general")
            if not row:
                return None
            entry = _entry_from_row(row)
            return entry if _is_fresh(entry, _GENERAL_TTL_HOURS) else None
        except Exception:
            # 로컬 테스트 DB가 migration 전이면 JSON mock 캐시로 계속 동작하게 한다.
            pass

    data = _load_json()
    entry = data.get(_general_json_key(user_id))
    if not entry or not _is_fresh(entry, _GENERAL_TTL_HOURS):
        return None
    return entry


def save_general_preference(user_id: int, preference: dict[str, Any]) -> None:
    """일반 선호도를 캐시에 저장한다."""
    if _can_try_database():
        try:
            _save_cache_row(
                user_id,
                preference_type="general",
                preference_data=dict(preference),
            )
            return
        except Exception:
            # DB 캐시를 쓸 수 없는 로컬 환경에서는 기존 JSON mock 파일을 사용한다.
            pass

    data = _load_json()
    data[_general_json_key(user_id)] = {
        **preference,
        "computed_at": datetime.now(UTC).isoformat(),
    }
    _save_json(data)


def get_keyword_preference(user_id: int, keywords: list[str]) -> Optional[list]:
    """키워드별 선호도 캐시를 조회한다. TTL 초과 시 None을 반환한다."""
    if not keywords:
        return None

    if _can_try_database():
        try:
            row = _get_cache_row(
                user_id,
                preference_type="keyword",
                keywords_key=_keywords_key(keywords),
            )
            if not row:
                return None
            entry = _entry_from_row(row)
            if not _is_fresh(entry, _KEYWORD_TTL_HOURS):
                return None
            return entry.get("keyword_history")
        except Exception:
            # 로컬 DB가 준비되지 않아도 memory_agent 테스트는 JSON 캐시로 검증한다.
            pass

    data = _load_json()
    entry = data.get(_keyword_json_key(user_id, keywords))
    if not entry or not _is_fresh(entry, _KEYWORD_TTL_HOURS):
        return None
    return entry.get("keyword_history")


def save_keyword_preference(user_id: int, keywords: list[str], keyword_history: list) -> None:
    """키워드별 선호도 캐시를 저장한다."""
    if not keywords:
        return

    if _can_try_database():
        try:
            _save_cache_row(
                user_id,
                preference_type="keyword",
                keywords_key=_keywords_key(keywords),
                preference_data={"keyword_history": keyword_history},
            )
            return
        except Exception:
            # DB 캐시 저장 실패 시에도 구매 플로우가 막히지 않도록 mock 캐시에 저장한다.
            pass

    data = _load_json()
    data[_keyword_json_key(user_id, keywords)] = {
        "keyword_history": keyword_history,
        "computed_at": datetime.now(UTC).isoformat(),
    }
    _save_json(data)


def invalidate_all_preferences(user_id: int) -> None:
    """구매 완료 후 해당 유저의 모든 선호도 캐시를 무효화한다."""
    if _can_try_database():
        try:
            _delete_cache_rows(user_id)
            return
        except Exception:
            # 로컬 DB가 없거나 migration 전이면 JSON mock 캐시만 비운다.
            pass

    data = _load_json()
    prefix = f"{user_id}:"
    for key in [key for key in data if key.startswith(prefix)]:
        data.pop(key)
    _save_json(data)


def invalidate_general_preference(user_id: int) -> None:
    """일반 선호도 캐시만 무효화한다."""
    if _can_try_database():
        try:
            _delete_cache_rows(user_id, preference_type="general")
            return
        except Exception:
            # 로컬 DB가 없거나 migration 전이면 JSON mock 캐시만 비운다.
            pass

    data = _load_json()
    data.pop(_general_json_key(user_id), None)
    _save_json(data)

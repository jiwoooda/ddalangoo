"""
DB Client — mock / real 두 모드를 명시적으로 선택한다 (mock_search.py의
SEARCH_MODE와 동일한 패턴). context_agent.py/reorder_agent.py가 DB에
접근하는 지점을 전부 여기로 모은다.

- mode="mock": mock_tools.py의 정적 데이터 사용. profile/general_preference는
  프로세스 메모리 dict에 저장 (재시작하면 초기화됨 — DB_MODE=mock은
  "DB 없이 개발/테스트" 용도지 영속성이 필요한 용도가 아니다).
- mode="real": 실제 Postgres(app.repositories.*)를 사용.

기본 mode는 DB_MODE 환경변수(mock|real, 기본값 mock)로 결정된다.
"""
import asyncio
import os
import sys
from datetime import datetime, UTC
from typing import Any, Literal

from src.tools.mock_tools import (
    mock_get_user,
    mock_get_default_address,
    mock_get_purchase_history,
    mock_keyword_search_history,
    mock_validate_product_url,
)

DbMode = Literal["mock", "real"]

_BACKEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)


def _default_db_mode() -> DbMode:
    value = os.getenv("DB_MODE", "mock").strip().lower()
    return "real" if value == "real" else "mock"


def _run_async_with_fresh_engine(coro_factory) -> Any:
    """
    sync 컨텍스트에서 async DB 작업 실행.
    매 호출마다 엔진을 새로 생성하고 dispose() — asyncpg 풀이 이전 루프에
    묶이는 'Event loop is closed' 오류를 방지한다.
    (context_agent.py/reorder_agent.py에 중복돼있던 걸 여기로 모음)
    """
    if _BACKEND_DIR not in sys.path:
        sys.path.insert(0, _BACKEND_DIR)

    async def _runner():
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        try:
            async with factory() as session:
                return await coro_factory(session)
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_runner())
    finally:
        loop.close()


# ── mock 모드 전용 in-memory 저장소 (profile/general_preference — DB 캐시 대응) ──
_mock_profile_store: dict[str, dict[str, Any]] = {}
_mock_general_preference_store: dict[str, dict[str, Any]] = {}


def get_user(user_id: str, mode: DbMode | None = None) -> dict[str, Any] | None:
    if (mode or _default_db_mode()) == "mock":
        return mock_get_user(user_id)

    async def _from_db(session):
        from app.repositories.user_repository import get_user_by_id_db
        return await get_user_by_id_db(session, int(user_id))
    try:
        return _run_async_with_fresh_engine(_from_db)
    except Exception:
        return None


def get_default_address(user_id: str, mode: DbMode | None = None) -> dict[str, Any] | None:
    if (mode or _default_db_mode()) == "mock":
        return mock_get_default_address(user_id)

    async def _from_db(session):
        from app.repositories.address_repository import get_default_address_by_user_id_db
        return await get_default_address_by_user_id_db(session, int(user_id))
    try:
        return _run_async_with_fresh_engine(_from_db)
    except Exception:
        return None


def get_purchase_histories(user_id: str, mode: DbMode | None = None) -> list[dict[str, Any]]:
    if (mode or _default_db_mode()) == "mock":
        return mock_get_purchase_history(user_id)

    async def _from_db(session):
        from app.repositories.purchase_history_repository import get_histories_by_user_id_db
        return await get_histories_by_user_id_db(session, int(user_id))
    try:
        return _run_async_with_fresh_engine(_from_db)
    except Exception:
        return []


def get_purchase_histories_by_keywords(
    user_id: str,
    keywords: list[str],
    limit: int = 5,
    mode: DbMode | None = None,
) -> list[dict[str, Any]]:
    if (mode or _default_db_mode()) == "mock":
        return mock_keyword_search_history(user_id, keywords, limit)

    async def _from_db(session):
        from app.repositories.purchase_history_repository import get_histories_by_keywords_db
        return await get_histories_by_keywords_db(session, int(user_id), keywords=keywords, limit=limit)
    try:
        return _run_async_with_fresh_engine(_from_db)
    except Exception:
        return []


def validate_product_url(url: str, mode: DbMode | None = None) -> bool:
    if (mode or _default_db_mode()) == "mock":
        return mock_validate_product_url(url)
    if not url:
        return False
    try:
        from app.services.reorder_memory_resolver import validate_product_url as _validate
        return _validate(url)
    except Exception:
        valid_domains = (
            "kurly.com", "coupang.com", "naver.com",
            "oliveyoung.co.kr", "musinsa.com",
        )
        return any(domain in url for domain in valid_domains)


def save_purchase_history_from_completed(
    user_id: str,
    completed_purchase: dict[str, Any],
    mode: DbMode | None = None,
) -> None:
    if (mode or _default_db_mode()) == "mock":
        # mock 결제 플로우(mock_place_order)가 결제 시점에 이미
        # MOCK_PURCHASE_HISTORY에 기록한다 — 여기서 별도로 할 일 없음.
        return
    order_id = completed_purchase.get("order_id")
    if not order_id:
        return

    async def _from_db(session):
        from app.repositories.purchase_history_repository import create_histories_from_order_db
        return await create_histories_from_order_db(session, order_id=int(order_id))
    try:
        _run_async_with_fresh_engine(_from_db)
    except Exception:
        pass


def get_profile(user_id: str, mode: DbMode | None = None) -> dict[str, Any] | None:
    """
    장기 프로필(알레르기 등). mock 모드는 프로세스 메모리에만 저장되므로
    재시작하면 비어있다 — 필요하면 save_profile로 다시 채워야 한다.
    """
    if (mode or _default_db_mode()) == "mock":
        return _mock_profile_store.get(str(user_id))
    try:
        from app.repositories import user_preference_repository
        return user_preference_repository.get_profile(int(user_id))
    except Exception:
        return None


def save_profile(user_id: str, profile: dict[str, Any], mode: DbMode | None = None) -> None:
    if (mode or _default_db_mode()) == "mock":
        # real 모드(user_preference_repository)는 computed_at을 자동으로
        # 붙여준다 — mock도 맞춰서 붙인다. RoutedSignal의 general_context
        # timestamp가 이 값을 쓴다 (context_agent._enrich_signals 참고).
        stamped = dict(profile)
        stamped["computed_at"] = datetime.now(UTC).isoformat()
        _mock_profile_store[str(user_id)] = stamped
        return
    try:
        from app.repositories import user_preference_repository
        user_preference_repository.save_profile(int(user_id), profile)
    except Exception:
        pass


def get_general_preference(user_id: str, mode: DbMode | None = None) -> dict[str, Any] | None:
    if (mode or _default_db_mode()) == "mock":
        return _mock_general_preference_store.get(str(user_id))
    try:
        from app.repositories import user_preference_repository
        return user_preference_repository.get_general_preference(int(user_id))
    except Exception:
        return None


def save_general_preference(user_id: str, preference: dict[str, Any], mode: DbMode | None = None) -> None:
    if (mode or _default_db_mode()) == "mock":
        _mock_general_preference_store[str(user_id)] = dict(preference)
        return
    try:
        from app.repositories import user_preference_repository
        user_preference_repository.save_general_preference(int(user_id), preference)
    except Exception:
        pass


def invalidate_purchase_derived_preferences(user_id: str, mode: DbMode | None = None) -> None:
    """구매 완료 후 general/keyword 선호도 캐시 무효화. profile은 건드리지 않는다."""
    if (mode or _default_db_mode()) == "mock":
        _mock_general_preference_store.pop(str(user_id), None)
        return
    try:
        from app.repositories import user_preference_repository
        user_preference_repository.invalidate_all_preferences(int(user_id))
    except Exception:
        pass

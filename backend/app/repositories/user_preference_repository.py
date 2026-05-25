"""
UserPreference 레포지토리 (mock / JSON 캐시).

memory_agent가 동기 컨텍스트에서 호출한다.
JSON 파일 기반으로 서버 재시작 후에도 캐시가 유지된다.

저장 키 구조:
  "{user_id}:general"          → 일반 선호도 (전체 구매이력 기반)
  "{user_id}:kw_{keywords}"   → 키워드별 선호도 (해당 키워드 이력 기반)

DB 연동은 백엔드 팀이 담당한다.
"""
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_data", "user_preferences.json")
_GENERAL_TTL_HOURS = 24
_KEYWORD_TTL_HOURS = 24


def _load() -> dict:
    if not os.path.exists(_JSON_PATH):
        return {}
    try:
        with open(_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        with open(_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def _is_fresh(entry: dict, ttl_hours: int) -> bool:
    try:
        computed_at = datetime.fromisoformat(entry["computed_at"])
        return datetime.now(UTC) - computed_at <= timedelta(hours=ttl_hours)
    except Exception:
        return False


def _general_key(user_id: int) -> str:
    return f"{user_id}:general"


def _keyword_key(user_id: int, keywords: list[str]) -> str:
    return f"{user_id}:kw_{'_'.join(sorted(keywords))}"


# ─────────────────────── 일반 선호도 ────────────────────────────

def get_general_preference(user_id: int) -> Optional[dict[str, Any]]:
    """캐시에서 일반 선호도를 조회한다. TTL 초과 시 None 반환."""
    data = _load()
    entry = data.get(_general_key(user_id))
    if not entry or not _is_fresh(entry, _GENERAL_TTL_HOURS):
        return None
    return entry


def save_general_preference(user_id: int, preference: dict[str, Any]) -> None:
    """일반 선호도를 캐시에 저장한다."""
    data = _load()
    data[_general_key(user_id)] = {**preference, "computed_at": datetime.now(UTC).isoformat()}
    _save(data)


# ─────────────────────── 키워드별 선호도 ────────────────────────

def get_keyword_preference(user_id: int, keywords: list[str]) -> Optional[list]:
    """캐시에서 키워드별 구매이력을 조회한다. TTL 초과 시 None 반환."""
    if not keywords:
        return None
    data = _load()
    entry = data.get(_keyword_key(user_id, keywords))
    if not entry or not _is_fresh(entry, _KEYWORD_TTL_HOURS):
        return None
    return entry.get("keyword_history")


def save_keyword_preference(user_id: int, keywords: list[str], keyword_history: list) -> None:
    """키워드별 구매이력을 캐시에 저장한다."""
    if not keywords:
        return
    data = _load()
    data[_keyword_key(user_id, keywords)] = {
        "keyword_history": keyword_history,
        "computed_at": datetime.now(UTC).isoformat(),
    }
    _save(data)


# ─────────────────────── 무효화 ─────────────────────────────────

def invalidate_all_preferences(user_id: int) -> None:
    """구매 완료 후 해당 유저의 모든 캐시를 무효화한다."""
    data = _load()
    prefix = f"{user_id}:"
    keys_to_delete = [k for k in data if k.startswith(prefix)]
    for k in keys_to_delete:
        data.pop(k)
    _save(data)


def invalidate_general_preference(user_id: int) -> None:
    """일반 선호도 캐시만 무효화한다."""
    data = _load()
    data.pop(_general_key(user_id), None)
    _save(data)

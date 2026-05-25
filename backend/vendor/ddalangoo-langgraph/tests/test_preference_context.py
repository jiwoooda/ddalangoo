"""
build_preference_context() + user_preference_repository 통합 테스트.

sqlalchemy 없는 테스트 환경에서도 동작하도록:
- purchase_history_repository → MagicMock (JSON 직접 주입)
- user_preference_repository → 실제 모듈 (sqlalchemy 불필요)
"""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.abspath(os.path.join(_TEST_DIR, ".."))
_BACKEND = os.path.abspath(os.path.join(_TEST_DIR, "../../../"))

for p in (_VENDOR, _BACKEND):
    if p not in sys.path:
        sys.path.insert(0, p)

# ─── mock purchase_history_repository 준비 ───────────────────────────────────
_PH_JSON = os.path.join(_BACKEND, "app", "mock_data", "purchase_histories.json")
with open(_PH_JSON, encoding="utf-8") as f:
    MOCK_HISTORIES = json.load(f)

_mock_ph = MagicMock()
_mock_ph.get_histories_by_user_id = lambda uid: [h for h in MOCK_HISTORIES if h["user_id"] == uid]

# ─── user_preference_repository 파일에서 직접 로드 (sqlalchemy 불필요) ───────
_upr_path = os.path.join(_BACKEND, "app", "repositories", "user_preference_repository.py")
_upr_spec = importlib.util.spec_from_file_location("app.repositories.user_preference_repository", _upr_path)
_upr = importlib.util.module_from_spec(_upr_spec)
_upr_spec.loader.exec_module(_upr)

# ─── sys.modules mock 등록 ────────────────────────────────────────────────────
_mock_app = MagicMock()
_mock_repos = MagicMock()
_mock_repos.purchase_history_repository = _mock_ph
_mock_repos.user_preference_repository = _upr

sys.modules.setdefault("app", _mock_app)
sys.modules["app.repositories"] = _mock_repos
sys.modules["app.repositories.purchase_history_repository"] = _mock_ph
sys.modules["app.repositories.user_preference_repository"] = _upr

# ─── 테스트 대상 임포트 ──────────────────────────────────────────────────────
from src.agents.memory_agent import _compute_general_preference, build_preference_context

# 캐시 파일 경로
_CACHE_PATH = os.path.join(_BACKEND, "app", "mock_data", "user_preferences.json")
USER_ID = "1"


def _clear_cache():
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({}, f)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _compute_general_preference() 직접 테스트
# ═══════════════════════════════════════════════════════════════════════════════

def test_compute_returns_expected_keys():
    """_compute_general_preference()가 필수 키를 모두 반환해야 한다."""
    result = _compute_general_preference(MOCK_HISTORIES)
    for key in ("preferred_brands", "price_range", "repurchase_patterns",
                "preferred_platform", "summary"):
        assert key in result, f"'{key}' 키가 없음"


def test_compute_preferred_platform_is_most_frequent():
    """preferred_platform이 실제 구매이력에서 가장 많은 플랫폼이어야 한다."""
    from collections import Counter
    result = _compute_general_preference(MOCK_HISTORIES)
    platforms = Counter(h.get("platform") for h in MOCK_HISTORIES if h.get("platform"))
    expected = platforms.most_common(1)[0][0]
    assert result["preferred_platform"] == expected


def test_compute_price_range():
    """price_range에 avg/min/max가 있어야 한다."""
    result = _compute_general_preference(MOCK_HISTORIES)
    pr = result["price_range"]
    assert "avg" in pr and "min" in pr and "max" in pr
    assert pr["min"] <= pr["avg"] <= pr["max"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. user_preference_repository (JSON 캐시) 직접 테스트
# ═══════════════════════════════════════════════════════════════════════════════

def test_repository_save_and_load():
    """저장 후 조회하면 같은 데이터가 나와야 한다."""
    _clear_cache()
    pref = {"preferred_brands": [{"brand": "CJ", "count": 3}], "summary": "test"}
    _upr.save_general_preference(1, pref)

    loaded = _upr.get_general_preference(1)
    assert loaded is not None
    assert loaded["summary"] == "test"
    assert "computed_at" in loaded


def test_repository_invalidate():
    """invalidate 후 조회하면 None이 반환돼야 한다."""
    _clear_cache()
    _upr.save_general_preference(1, {"summary": "temp"})
    _upr.invalidate_general_preference(1)
    assert _upr.get_general_preference(1) is None


def test_repository_keyword_save_and_load():
    """키워드별 선호도를 저장하고 조회할 수 있어야 한다."""
    _clear_cache()
    kw_hist = [{"product_name": "두부 300g", "brand": "풀무원", "price": 2490, "platform": "kurly"}]
    _upr.save_keyword_preference(1, ["두부"], kw_hist)

    loaded = _upr.get_keyword_preference(1, ["두부"])
    assert loaded is not None
    assert loaded[0]["product_name"] == "두부 300g"


def test_repository_invalidate_all():
    """invalidate_all 후 일반·키워드 선호도 모두 삭제돼야 한다."""
    _clear_cache()
    _upr.save_general_preference(1, {"summary": "g"})
    _upr.save_keyword_preference(1, ["딸기"], [{"product_name": "딸기"}])
    _upr.invalidate_all_preferences(1)

    assert _upr.get_general_preference(1) is None
    assert _upr.get_keyword_preference(1, ["딸기"]) is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. build_preference_context() 통합 흐름
# ═══════════════════════════════════════════════════════════════════════════════

def test_build_returns_expected_keys():
    """build_preference_context()가 필수 키를 모두 반환해야 한다."""
    _clear_cache()
    result = build_preference_context(USER_ID, ["딸기"])
    assert isinstance(result, dict) and result, "결과가 비어있음"
    for key in ("preferred_brands", "price_range", "repurchase_patterns",
                "preferred_platform", "summary", "keyword_history"):
        assert key in result, f"'{key}' 키가 없음"


def test_build_saves_to_cache():
    """첫 호출 후 JSON 파일에 캐시가 저장돼야 한다."""
    _clear_cache()
    build_preference_context(USER_ID, [])

    with open(_CACHE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    assert f"{USER_ID}:general" in data, "캐시 파일에 저장 안 됨"
    assert "computed_at" in data[f"{USER_ID}:general"]


def test_build_cache_hit(monkeypatch):
    """두 번째 호출은 캐시에서 읽어야 한다 (재계산 없음)."""
    _clear_cache()
    build_preference_context(USER_ID, [])  # 캐시 생성

    import src.agents.memory_agent as ma
    original = ma._compute_general_preference
    call_count = {"n": 0}

    def spy(histories):
        call_count["n"] += 1
        return original(histories)

    monkeypatch.setattr(ma, "_compute_general_preference", spy)
    build_preference_context(USER_ID, [])

    assert call_count["n"] == 0, "캐시 히트인데 재계산됨"


def test_build_recomputes_after_invalidate(monkeypatch):
    """invalidate 후 다음 호출에서 재계산돼야 한다."""
    _clear_cache()
    build_preference_context(USER_ID, [])
    _upr.invalidate_all_preferences(int(USER_ID))

    import src.agents.memory_agent as ma
    original = ma._compute_general_preference
    call_count = {"n": 0}

    def spy(histories):
        call_count["n"] += 1
        return original(histories)

    monkeypatch.setattr(ma, "_compute_general_preference", spy)
    build_preference_context(USER_ID, [])

    assert call_count["n"] == 1, "invalidate 후 재계산 안 됨"


def test_keyword_history_filtered():
    """keyword_history는 키워드 매칭 이력만 포함해야 한다."""
    _clear_cache()
    result = build_preference_context(USER_ID, ["딸기"])
    kw_hist = result.get("keyword_history", [])

    assert isinstance(kw_hist, list) and kw_hist, "keyword_history가 비어있음"
    for item in kw_hist:
        name = (item.get("product_name") or "").lower()
        assert "딸기" in name or "strawberry" in name, (
            f"키워드와 무관한 이력 포함: {item['product_name']}"
        )


def test_keyword_history_cached_on_second_call(monkeypatch):
    """두 번째 키워드 호출은 캐시에서 읽어야 한다."""
    _clear_cache()
    build_preference_context(USER_ID, ["딸기"])  # 캐시 생성

    filter_count = {"n": 0}
    import src.agents.memory_agent as ma

    original_build = ma.build_preference_context

    def spy_filter(histories, keywords):
        # keyword_history 계산 부분만 감시 — 실제론 내부 리스트 컴프리헨션이므로
        # get_keyword_preference 호출 여부로 판단
        filter_count["n"] += 1

    # get_keyword_preference가 캐시 히트를 반환하는지 확인
    original_get = _upr.get_keyword_preference

    def spy_get(uid, kws):
        result = original_get(uid, kws)
        filter_count["n"] = 1 if result is not None else 0
        return result

    monkeypatch.setattr(_upr, "get_keyword_preference", spy_get)
    build_preference_context(USER_ID, ["딸기"])

    assert filter_count["n"] == 1, "두 번째 호출에서 캐시 히트가 아님"


def test_keyword_history_empty_when_no_match():
    """매칭 이력 없으면 keyword_history가 빈 리스트여야 한다."""
    _clear_cache()
    result = build_preference_context(USER_ID, ["노트북"])
    assert result.get("keyword_history") == []

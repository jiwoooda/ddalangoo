"""
Context Agent tier1(안전)/tier2(명시적 배제) + Priority Resolver + 세션
안전정보 동기화 유닛 테스트.

실 DB가 없는 개발 환경을 고려해 DB/LLM 호출을 monkeypatch로 대체하고
로직(merge, 필터링, 우선순위 재판정)만 검증한다.
"""
import src.agents.context_agent as context_agent
from src.agents.context_agent import (
    build_preference_context,
    context_agent_node,
)
from src.agents.product_agent import _fails_safety_constraints, _filter_results
from src.state.routed_signal import RoutedSignal
from src.state.schema import get_default_shopping_state
from src.tools import db_client
from src.utils.priority_resolver import rank_by_recency, resolve_precedence


def _signal(value, source="session_smalltalk", decision_role="soft_preference", evidence="", timestamp=None, signal_id="sig_0"):
    return RoutedSignal(
        signal_id=signal_id, value=value, source=source,
        evidence=evidence, decision_role=decision_role, timestamp=timestamp,
    )


# ── product_agent tier1 필터 (DB/LLM 무관, 순수 함수) ──────────────────────

def test_fails_safety_constraints_matches_allergen():
    product = {"nutrition_info": {"allergens": ["우유"]}}
    assert _fails_safety_constraints(product, ["우유"]) is True


def test_fails_safety_constraints_no_overlap_passes():
    product = {"nutrition_info": {"allergens": ["참깨"]}}
    assert _fails_safety_constraints(product, ["우유"]) is False


def test_fails_safety_constraints_missing_nutrition_conservative_exclude():
    """nutrition_info 자체가 없으면(mcp 모드 연동 전) 보수적으로 배제."""
    product = {}
    assert _fails_safety_constraints(product, ["우유"]) is True


def test_fails_safety_constraints_empty_list_never_excludes():
    """safety_constraints가 없으면(프로필 없는 사용자) 기존 동작 그대로."""
    product = {}
    assert _fails_safety_constraints(product, []) is False


def test_filter_results_tier2_matches_brand_field_not_just_product_name():
    """
    negative feedback으로 뽑힌 exclude_additions는 브랜드명일 수 있는데,
    브랜드가 product_name 문자열에 안 박혀있는 상품도 걸러져야 한다.
    """
    products = [
        {"product_name": "유정란 15구", "brand": "동물복지", "price": 8900, "product_url": "u1"},
        {"product_name": "무항생제 계란", "brand": "풀무원", "price": 5000, "product_url": "u2"},
    ]
    result = _filter_results(products, exclude_keywords=["동물복지"], safety_constraints=[])
    names = {p["product_name"] for p in result}
    assert names == {"무항생제 계란"}


def test_filter_results_applies_tier1_and_tier2_together():
    products = [
        {"product_name": "우유 1L", "price": 3000, "product_url": "u1", "nutrition_info": {"allergens": ["우유"]}},
        {"product_name": "무항생제 계란", "price": 5000, "product_url": "u2", "nutrition_info": {"allergens": ["계란"]}},
        {"product_name": "죽향 딸기", "price": 12000, "product_url": "u3", "nutrition_info": {"allergens": []}},
    ]
    result = _filter_results(products, exclude_keywords=["죽향"], safety_constraints=["우유"])
    names = {p["product_name"] for p in result}
    assert names == {"무항생제 계란"}  # 우유=tier1 배제, 죽향=tier2(exclude_keywords) 배제


# ── III: Priority Resolver (순수 함수) ──────────────────────────────────

def test_resolve_precedence_intent_overrides_stale_exclusion():
    """예전엔 '나이키 싫음'이었지만 이번 Intent가 나이키를 다시 명시하면 무효화."""
    signals = [_signal("나이키", decision_role="explicit_exclusion")]
    result = resolve_precedence(["나이키", "운동화"], signals)
    assert result["effective_exclusions"] == []
    assert len(result["overridden_exclusions"]) == 1


def test_resolve_precedence_exclusion_survives_when_not_re_requested():
    signals = [_signal("나이키", decision_role="explicit_exclusion")]
    result = resolve_precedence(["운동화"], signals)
    assert len(result["effective_exclusions"]) == 1
    assert result["overridden_exclusions"] == []


def test_resolve_precedence_soft_preference_passes_through_unchanged():
    signals = [_signal("가성비", decision_role="soft_preference")]
    result = resolve_precedence(["딸기"], signals)
    assert result["active_soft_preferences"] == signals


def test_resolve_precedence_retrieval_passes_through():
    signals = [_signal("락토프리", decision_role="retrieval")]
    result = resolve_precedence(["우유"], signals)
    assert result["retrieval_signals"] == signals


# ── rank_by_recency: timestamp 없는 general_context/session_smalltalk의 순서 판단 ──

def test_rank_by_recency_session_smalltalk_beats_general_context():
    """session이 profile/구매이력보다 항상 최근으로 취급된다."""
    general = _signal("프리미엄만", source="general_context")
    session = _signal("이번엔 저렴한걸로", source="session_smalltalk")
    ranked = rank_by_recency([general, session])
    assert ranked[0] is session


def test_rank_by_recency_purchase_history_uses_actual_timestamp():
    older = _signal("프리미엄", source="purchase_history", timestamp="2025-01-01T00:00:00")
    newer = _signal("최저가", source="purchase_history", timestamp="2026-01-01T00:00:00")
    ranked = rank_by_recency([older, newer])
    assert ranked[0] is newer


def test_rank_by_recency_session_smalltalk_tie_break_by_list_order():
    """timestamp 없는 session_smalltalk끼리는 등장(리스트) 순서로 — 뒤에 온 게 더 최근."""
    first_said = _signal("저당으로", source="session_smalltalk")
    said_later = _signal("그냥 아무거나", source="session_smalltalk")
    ranked = rank_by_recency([first_said, said_later])
    assert ranked[0] is said_later


def test_rank_by_recency_session_smalltalk_beats_purchase_history_even_with_timestamp():
    """카테고리 우선순위가 우선 — purchase_history가 아무리 최근 구매여도 session이 이긴다."""
    recent_purchase = _signal("프리미엄", source="purchase_history", timestamp="2026-07-13T00:00:00")
    session = _signal("이번엔 저렴한걸로", source="session_smalltalk")
    ranked = rank_by_recency([recent_purchase, session])
    assert ranked[0] is session


# ── I: 세션 안전정보 동기화 (LLM monkeypatch) ──────────────────────────────

def test_detect_safety_trigger_matches_keyword():
    messages = [{"role": "user", "content": "저 땅콩 알레르기 있어요"}]
    assert context_agent._detect_safety_trigger(messages) is True


def test_detect_safety_trigger_no_match():
    messages = [{"role": "user", "content": "딸기 좀 싸게 사줘"}]
    assert context_agent._detect_safety_trigger(messages) is False


def test_sync_safety_from_session_no_trigger_skips_llm_call(monkeypatch):
    """트리거 키워드가 없으면 LLM 호출 자체를 안 한다 (매 요청 비용 방지)."""
    monkeypatch.setattr(context_agent, "_get_llm", lambda: (_ for _ in ()).throw(AssertionError("LLM 호출되면 안 됨")))
    result = context_agent._sync_safety_from_session("1", {"allergens": ["우유"]}, [{"role": "user", "content": "딸기 사줘"}])
    assert result == {"allergens": ["우유"]}


def test_sync_safety_from_session_merges_and_persists(monkeypatch):
    """트리거되면 LLM 결과를 기존 profile과 합쳐서 db_client.save_profile로 즉시 저장."""
    from src.agents.context_agent import SafetySignalUpdate
    fake_result = SafetySignalUpdate(new_allergens=["땅콩"], new_diet_restrictions=[])
    saved = {}

    class _FakeBoundLLM:
        def invoke(self, *a, **kw):
            return fake_result

    class _FakeLLM:
        def with_structured_output(self, *a, **kw):
            return _FakeBoundLLM()

    monkeypatch.setattr(context_agent, "_get_llm", lambda: _FakeLLM())
    monkeypatch.setattr(db_client, "save_profile", lambda user_id, profile, mode=None: saved.update(profile))

    result = context_agent._sync_safety_from_session(
        "1", {"allergens": ["우유"], "diet_restrictions": []},
        [{"role": "user", "content": "저 땅콩 알레르기 있어요"}],
    )

    assert set(result["allergens"]) == {"우유", "땅콩"}
    assert set(saved["allergens"]) == {"우유", "땅콩"}


# ── context_agent build_preference_context (DB/LLM monkeypatch) ───────────

def test_build_preference_context_returns_safety_even_without_purchase_history(monkeypatch):
    """
    안전 문제 수정: 구매이력이 없는 신규 유저라도 profile의 안전 제약은
    항상 반환돼야 한다 (예전엔 히스토리 없으면 통째로 빈 dict를 반환했음).
    """
    monkeypatch.setattr(context_agent, "_fetch_purchase_histories", lambda user_id: [])
    monkeypatch.setattr(db_client, "get_profile", lambda user_id, mode=None: {"allergens": ["땅콩"], "diet_restrictions": []})

    result = build_preference_context("1", ["과자"], messages=[])

    assert result["safety_constraints"] == ["땅콩"]


def test_build_preference_context_merges_profile_and_routed_signals(monkeypatch):
    fake_histories = [
        {
            "product_name": "유정란 15구", "brand": "동물복지", "platform": "kurly",
            "keyword": "계란", "category": "축산", "price_at_purchase": 8900,
            "satisfaction": 1, "memo": "깨진 게 많아서 다신 안 삼", "purchased_at": "2026-01-01T00:00:00",
        },
    ]
    monkeypatch.setattr(context_agent, "_fetch_purchase_histories", lambda user_id: fake_histories)

    monkeypatch.setattr(db_client, "get_general_preference", lambda user_id, mode=None: None)
    monkeypatch.setattr(db_client, "save_general_preference", lambda user_id, preference, mode=None: None)
    monkeypatch.setattr(
        db_client, "get_profile",
        lambda user_id, mode=None: {"allergens": ["우유"], "diet_restrictions": []},
    )
    monkeypatch.setattr(context_agent, "_generate_llm_summary", lambda *a, **kw: "요약")

    fake_signals = [
        _signal("저당", decision_role="retrieval", source="general_context"),
        _signal("유정란", decision_role="explicit_exclusion", source="purchase_history"),
        _signal("가성비", decision_role="soft_preference", source="session_smalltalk"),
    ]
    monkeypatch.setattr(context_agent, "_classify_context", lambda *a, **kw: fake_signals)

    result = build_preference_context("1", ["계란"], messages=[])

    assert result["safety_constraints"] == ["우유"]
    assert result["exclude_additions"] == ["유정란"]
    assert result["keyword_additions"] == ["저당"]
    assert result["soft_preferences"][0]["value"] == "가성비"
    assert result["keyword_summary"] == "가성비"


def test_build_preference_context_intent_overrides_exclusion(monkeypatch):
    """이번 keywords가 과거 explicit_exclusion과 같은 대상을 다시 요청하면 무효화."""
    fake_histories = [
        {
            "product_name": "나이키 운동화", "brand": "나이키", "platform": "naver",
            "keyword": "운동화", "category": "신발", "price_at_purchase": 89000,
            "satisfaction": None, "memo": None, "purchased_at": "2026-01-01T00:00:00",
        },
    ]
    monkeypatch.setattr(context_agent, "_fetch_purchase_histories", lambda user_id: fake_histories)
    monkeypatch.setattr(db_client, "get_general_preference", lambda user_id, mode=None: None)
    monkeypatch.setattr(db_client, "save_general_preference", lambda user_id, preference, mode=None: None)
    monkeypatch.setattr(db_client, "get_profile", lambda user_id, mode=None: None)
    monkeypatch.setattr(context_agent, "_generate_llm_summary", lambda *a, **kw: "요약")

    fake_signals = [_signal("나이키", decision_role="explicit_exclusion", source="purchase_history")]
    monkeypatch.setattr(context_agent, "_classify_context", lambda *a, **kw: fake_signals)

    result = build_preference_context("1", ["나이키", "운동화"], messages=[])

    assert result["exclude_additions"] == []
    assert len(result["overridden_exclusions"]) == 1


# ── context_agent_node: state.keywords/exclude_keywords 병합 ──────────────

def test_context_agent_node_merges_keywords_and_exclude(monkeypatch):
    fake_recommendation_context = {
        "purchase_count": 1,
        "retrieval_mode": "keyword_collective",
        "preference_context": {
            "_cache_hit": False,
            "keyword_additions": ["저당"],
            "exclude_additions": ["유정란"],
            "safety_constraints": ["우유"],
            "soft_preferences": [],
        },
    }
    monkeypatch.setattr(
        context_agent, "get_recommendation_context",
        lambda **kwargs: fake_recommendation_context,
    )

    state = get_default_shopping_state("1", "sess")
    state.update(intent="buy", keywords=["계란"], exclude_keywords=["품절"])

    result = context_agent_node(state)

    assert result["keywords"] == ["계란", "저당"]
    assert set(result["exclude_keywords"]) == {"품절", "유정란", "우유"}


def test_context_agent_node_no_duplicate_on_repeat(monkeypatch):
    """이미 keywords/exclude_keywords에 있는 값은 중복 추가되지 않는다."""
    fake_recommendation_context = {
        "purchase_count": 0,
        "retrieval_mode": "keyword_collective",
        "preference_context": {
            "_cache_hit": False,
            "keyword_additions": ["계란"],
            "exclude_additions": ["우유"],
            "safety_constraints": [],
            "soft_preferences": [],
        },
    }
    monkeypatch.setattr(
        context_agent, "get_recommendation_context",
        lambda **kwargs: fake_recommendation_context,
    )

    state = get_default_shopping_state("1", "sess")
    state.update(intent="buy", keywords=["계란"], exclude_keywords=["우유"])

    result = context_agent_node(state)

    assert result["keywords"] == ["계란"]
    assert result["exclude_keywords"] == ["우유"]

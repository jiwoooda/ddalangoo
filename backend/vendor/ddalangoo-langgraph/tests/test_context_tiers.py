"""
Context Agent tier1(안전)/tier2(명시적 배제) 연동 유닛 테스트.

실 DB가 없는 개발 환경을 고려해 DB/LLM 호출을 monkeypatch로 대체하고
로직(merge, 필터링)만 검증한다.
"""
import src.agents.context_agent as context_agent
from src.agents.context_agent import (
    ContextClassificationLLM,
    build_preference_context,
    context_agent_node,
)
from src.agents.product_agent import _fails_safety_constraints, _filter_results
from src.state.schema import get_default_shopping_state
from src.tools import db_client


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


def test_filter_results_applies_tier1_and_tier2_together():
    products = [
        {"product_name": "우유 1L", "price": 3000, "product_url": "u1", "nutrition_info": {"allergens": ["우유"]}},
        {"product_name": "무항생제 계란", "price": 5000, "product_url": "u2", "nutrition_info": {"allergens": ["계란"]}},
        {"product_name": "죽향 딸기", "price": 12000, "product_url": "u3", "nutrition_info": {"allergens": []}},
    ]
    result = _filter_results(products, exclude_keywords=["죽향"], safety_constraints=["우유"])
    names = {p["product_name"] for p in result}
    assert names == {"무항생제 계란"}  # 우유=tier1 배제, 죽향=tier2(exclude_keywords) 배제


# ── context_agent build_preference_context (DB/LLM monkeypatch) ───────────

def test_build_preference_context_merges_profile_and_classification(monkeypatch):
    fake_histories = [
        {
            "product_name": "유정란 15구", "brand": "동물복지", "platform": "kurly",
            "keyword": "계란", "category": "축산", "price_at_purchase": 8900,
            "satisfaction": 1, "memo": "깨진 게 많아서 다신 안 삼",
        },
    ]
    monkeypatch.setattr(context_agent, "_fetch_purchase_histories", lambda user_id: fake_histories)

    # DB 접근은 이제 db_client(mock/real 모드 전환)를 경유한다 — 모드와
    # 무관하게 로직만 검증하려면 db_client 함수를 직접 patch한다.
    monkeypatch.setattr(db_client, "get_general_preference", lambda user_id, mode=None: None)
    monkeypatch.setattr(db_client, "save_general_preference", lambda user_id, preference, mode=None: None)
    monkeypatch.setattr(
        db_client, "get_profile",
        lambda user_id, mode=None: {"allergens": ["우유"], "diet_restrictions": []},
    )
    monkeypatch.setattr(context_agent, "_generate_llm_summary", lambda *a, **kw: "요약")

    fake_classification = ContextClassificationLLM(
        keyword_additions=["저당"],
        exclude_additions=["유정란"],
        soft_preferences=["가성비"],
    )
    monkeypatch.setattr(context_agent, "_classify_context", lambda *a, **kw: fake_classification)

    result = build_preference_context("1", ["계란"], messages=[])

    assert result["safety_constraints"] == ["우유"]
    assert result["exclude_additions"] == ["유정란"]
    assert result["keyword_additions"] == ["저당"]
    assert result["soft_preferences"] == ["가성비"]
    assert result["keyword_summary"] == "가성비"


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

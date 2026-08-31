"""WON-37 Unit 1 — 카테고리별 초기화 필드셋 정의 검증.

이 유닛은 상수/헬퍼만 추가한다. 아직 어떤 노드도 호출하지 않으므로 회귀는
있으면 안 된다. 여기서는 (a) 각 헬퍼가 반환하는 dict 의 키가 대응 상수와
정확히 일치하고, (b) 초기화 값이 get_default_shopping_state() 기본값과
같고, (c) 4개 카테고리가 서로 겹치지 않으며, (d) 기존 5개 초기화 지점이
건드리는 "데이터 필드"를 빠짐없이 덮는지 확인한다.
"""
from src.state import schema
from src.state.schema import (
    PRODUCT_CONTEXT_RESET_FIELDS,
    PURCHASE_FLOW_RESET_FIELDS,
    CART_CLEAR_FIELDS,
    TURN_OBSERVABILITY_RESET_FIELDS,
    CART_CLEAR_REQUIRES_MOCK_CLEAR_CART,
    product_context_reset,
    purchase_flow_reset,
    cart_clear,
    turn_observability_reset,
    get_default_shopping_state,
)

_HELPERS = {
    "product_context": (product_context_reset, PRODUCT_CONTEXT_RESET_FIELDS),
    "purchase_flow": (purchase_flow_reset, PURCHASE_FLOW_RESET_FIELDS),
    "cart_clear": (cart_clear, CART_CLEAR_FIELDS),
    "turn_observability": (turn_observability_reset, TURN_OBSERVABILITY_RESET_FIELDS),
}

EXPECTED = {
    "product_context": {
        "keywords", "search_query", "exclude_keywords", "negative_constraints",
        "quantity", "condition", "product_request",
        "override_platform", "target_platforms", "tried_platforms", "selected_platform",
        "search_results", "scored_products", "recommended_products",
        "current_product_index", "selected_product", "product_url",
        "explanation", "highlight_specs",
    },
    "purchase_flow": {
        "pending_action", "payment_idempotency_key",
        "queue_items", "current_queue_index", "queue_source", "queue_clear_existing",
        "cart_operations", "recipe_dish", "recipe_people",
        "recommendation_context", "reorder_resolution",
    },
    "cart_clear": {"cart_items"},
    "turn_observability": {
        "degraded_mode", "degradation_reason", "failure_stage",
        "ranking_mode", "source_used",
    },
}


def test_helper_keys_match_constant_and_spec():
    for name, (fn, const) in _HELPERS.items():
        keys = set(fn())
        assert keys == set(const), f"{name}: helper keys != constant"
        assert keys == EXPECTED[name], f"{name}: helper keys != spec"


def test_reset_values_match_get_default():
    default = get_default_shopping_state("u1", "s1")
    for name, (fn, _const) in _HELPERS.items():
        for k, v in fn().items():
            assert v == default[k], f"{name}.{k}: reset={v!r} != default={default[k]!r}"


def test_helpers_return_fresh_mutable_containers():
    """헬퍼는 매 호출마다 새 list/dict 를 내야 한다(공유 기본값 오염 방지)."""
    for fn, _const in _HELPERS.values():
        a, b = fn(), fn()
        for k, v in a.items():
            if isinstance(v, (list, dict)):
                assert v is not b[k], f"{k}: 같은 컨테이너 객체 재사용"


def test_four_categories_are_disjoint():
    sets = [set(fn()) for fn, _c in _HELPERS.values()]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert not (sets[i] & sets[j]), f"카테고리 {i}/{j} 필드 중복: {sets[i] & sets[j]}"


def test_covers_existing_reset_points_data_fields():
    """기존 5개 초기화 지점이 건드리는 필드 중, 상황별로 값이 달라지는
    플로우 제어 필드를 뺀 나머지(데이터 필드)는 4개 카테고리 합집합이 전부 덮어야 한다."""
    union = set().union(*(set(fn()) for fn, _c in _HELPERS.values()))

    # 플로우 제어 / 세션 정체성 — 어느 카테고리에도 안 넣기로 한 필드(설계 결정)
    flow_control = {
        "stage", "intent", "error", "last_agent", "messages",
        "confidence", "immediate_response", "needs_clarification",
        "clarification_reason", "recommend_from_profile", "fallback_stuck_turns",
        "session_id", "conversation_id", "user_id",
    }

    cancel_node_fields = {
        "stage", "intent", "error", "pending_action", "last_agent",
        "keywords", "search_results", "scored_products", "recommended_products",
        "selected_product", "product_url", "explanation", "highlight_specs",
        "current_product_index", "quantity", "reorder_resolution", "cart_items",
        "payment_idempotency_key",
    }
    ask_what_to_buy_fields = {
        "pending_action", "stage", "keywords", "search_results", "selected_product",
        "reorder_resolution", "error", "quantity", "product_url",
        "current_product_index", "explanation", "highlight_specs",
        "scored_products", "recommended_products",
    }
    recover_result_fields = {
        "search_results", "selected_product", "product_url", "explanation",
        "highlight_specs", "current_product_index", "pending_action", "quantity",
    }
    turn_obs_fields = {
        "degraded_mode", "degradation_reason", "failure_stage",
        "ranking_mode", "source_used",
    }

    for site_name, fields in [
        ("cancel_node", cancel_node_fields),
        ("ask_what_to_buy_node", ask_what_to_buy_fields),
        ("_recover_result", recover_result_fields),
        ("reset_turn_observability_node", turn_obs_fields),
    ]:
        missing = (fields - flow_control) - union
        assert not missing, f"{site_name}: 어느 카테고리에도 없는 데이터 필드 {missing}"


def test_newly_found_fields_all_assigned():
    """조사에서 '어느 초기화 지점에도 없던' 필드가 4개 카테고리 중 하나에 배정됐는지."""
    union = set().union(*(set(fn()) for fn, _c in _HELPERS.values()))
    newly_found = {
        "product_request", "search_query", "exclude_keywords", "negative_constraints",
        "override_platform", "target_platforms", "tried_platforms", "selected_platform",
        "queue_items", "current_queue_index", "queue_source", "queue_clear_existing",
        "recipe_dish", "recipe_people", "cart_operations", "recommendation_context",
    }
    assert newly_found <= union, f"미배정 신규 필드: {newly_found - union}"


def test_all_fieldset_keys_are_real_shoppingstate_fields():
    valid = set(schema.ShoppingState.__annotations__)
    union = set().union(*(set(fn()) for fn, _c in _HELPERS.values()))
    assert union <= valid, f"ShoppingState 에 없는 필드: {union - valid}"


def test_cart_clear_flags_mock_call_required():
    assert CART_CLEAR_REQUIRES_MOCK_CLEAR_CART is True

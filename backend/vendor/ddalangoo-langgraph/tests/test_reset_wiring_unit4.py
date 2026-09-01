"""WON-37 Unit 4 — 5번째 지점(reset_turn_observability_node) 배선 검증
+ 5개 초기화 지점 전체가 카테고리 함수 기반으로 통일됐는지 소스 레벨 확인.
"""
import inspect

from src.state import schema
from src.state.schema import (
    turn_observability_reset,
    TURN_OBSERVABILITY_RESET_FIELDS,
    get_default_shopping_state,
)
from src.agents.nodes import reset_turn_observability_node


def test_reset_turn_observability_node_uses_helper():
    result = reset_turn_observability_node({})
    assert result == turn_observability_reset()
    assert set(result) == set(TURN_OBSERVABILITY_RESET_FIELDS)
    default = get_default_shopping_state("u", "s")
    for k, v in result.items():
        assert v == default[k], f"{k}: {v!r} != default {default[k]!r}"


def test_all_five_reset_sites_call_category_helpers():
    """5개 초기화 지점의 소스에 카테고리 함수 호출이 들어있는지(손 나열 제거)."""
    import src.agents.nodes as nodes_mod
    import src.payment.node as payment_mod
    import src.agents.fallback_orchestrator as fo_mod

    # 실제 '호출/스프레드'만 본다 — 주석에서 함수명을 언급하는 건 무시.
    def _spreads(src, name):
        return f"**{name}()" in src or f"updates.update({name}())" in src

    cancel_src = inspect.getsource(nodes_mod.cancel_node)
    assert _spreads(cancel_src, "product_context_reset") and _spreads(cancel_src, "purchase_flow_reset")
    assert _spreads(cancel_src, "cart_clear")  # 장바구니 실제 삭제 지점

    askwtb_src = inspect.getsource(nodes_mod.ask_what_to_buy_node)
    assert _spreads(askwtb_src, "product_context_reset") and _spreads(askwtb_src, "purchase_flow_reset")
    assert not _spreads(askwtb_src, "cart_clear")  # 장바구니 유지 지점

    turn_src = inspect.getsource(nodes_mod.reset_turn_observability_node)
    assert "turn_observability_reset()" in turn_src

    pay_src = inspect.getsource(payment_mod.payment_agent_node)
    assert _spreads(pay_src, "product_context_reset") and _spreads(pay_src, "purchase_flow_reset")
    assert _spreads(pay_src, "cart_clear")  # 결제완료: 장바구니 삭제 동반

    recover_src = inspect.getsource(fo_mod._recover_result)
    assert _spreads(recover_src, "product_context_reset") and _spreads(recover_src, "purchase_flow_reset")
    assert not _spreads(recover_src, "cart_clear")  # goal-shift: 장바구니 유지

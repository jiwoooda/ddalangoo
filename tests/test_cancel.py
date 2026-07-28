"""
Cancel / Interrupt 기능 unit tests.
LLM·Playwright 없이 순수 로직만 검증.

커버리지:
  1. cancel_node — 메시지·state 리셋
  2. router.route() — 모든 stage에서 cancel → "cancel"
  3. webview_tool — request_cancel / _check_cancel / _clear_cancel
  4. payment_agent_node — webview cancelled 결과 처리
"""
import threading
import pytest
from src.state.schema import get_default_shopping_state
from src.agents.nodes import cancel_node
from src.graph.router import route


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def make_state(**overrides) -> dict:
    state = get_default_shopping_state("user_test", "session_test")
    state.update(overrides)
    return state


MOCK_PRODUCT = {
    "product_name": "설향 딸기 500g",
    "price": 12900,
    "platform": "kurly",
    "product_url": "https://www.kurly.com/goods/1234",
}


# ══════════════════════════════════════════════
# 1. cancel_node
# ══════════════════════════════════════════════

class TestCancelNode:
    def test_no_cart_message(self):
        """장바구니 없으면 단순 취소 멘트."""
        state = make_state(stage="product_confirming", cart_items=[])
        result = cancel_node(state)
        assert result["pending_action"]["message"] == "알겠어요~ 필요하면 언제든 말씀해주세요!"

    def test_with_cart_message(self):
        """장바구니 있으면 담아둔 것 유지 안내."""
        state = make_state(
            stage="payment_processing",
            cart_items=[{"product_name": "딸기", "price": 12900, "quantity": 1, "total": 12900}],
        )
        result = cancel_node(state)
        assert "장바구니에 담아둔 건 그대로 있을 거에요" in result["pending_action"]["message"]

    def test_stage_reset_to_idle(self):
        """stage가 idle로 리셋되어야 한다."""
        state = make_state(stage="payment_processing")
        result = cancel_node(state)
        assert result["stage"] == "idle"

    def test_search_state_cleared(self):
        """검색 관련 state가 모두 초기화되어야 한다."""
        state = make_state(
            stage="product_confirming",
            keywords=["딸기"],
            search_results=[{"product_name": "딸기"}],
            scored_products=[{"product_name": "딸기"}],
            recommended_products=[{"product_name": "딸기"}],
            selected_product=MOCK_PRODUCT,
            product_url="https://www.kurly.com/goods/1234",
            quantity=2,
            reorder_resolution={"resolution_type": "resolved"},
        )
        result = cancel_node(state)
        assert result["keywords"] == []
        assert result["search_results"] == []
        assert result["scored_products"] == []
        assert result["recommended_products"] == []
        assert result["selected_product"] is None
        assert result["product_url"] is None
        assert result["quantity"] is None
        assert result["reorder_resolution"] is None

    def test_intent_cleared(self):
        state = make_state(intent="confirm", stage="payment_processing")
        result = cancel_node(state)
        assert result["intent"] is None

    def test_error_cleared(self):
        state = make_state(stage="product_confirming", error="some_error")
        result = cancel_node(state)
        assert result["error"] is None

    def test_last_agent_set(self):
        state = make_state(stage="searching")
        result = cancel_node(state)
        assert result["last_agent"] == "cancel"


# ══════════════════════════════════════════════
# 2. router — cancel은 stage 무관하게 "cancel"
# ══════════════════════════════════════════════

class TestRouterCancel:
    STAGES = ["idle", "searching", "product_confirming", "cart_shopping", "payment_processing"]

    @pytest.mark.parametrize("stage", STAGES)
    def test_cancel_always_routes_to_cancel_node(self, stage):
        state = make_state(intent="cancel", stage=stage, confidence=0.9, needs_clarification=False)
        assert route(state) == "cancel", f"stage={stage}에서 cancel이 cancel_node로 가야 함"

    def test_cancel_not_end(self):
        """예전 동작(end) 회귀 방지."""
        state = make_state(intent="cancel", stage="idle", confidence=0.9, needs_clarification=False)
        assert route(state) != "end"

    def test_cancel_not_interrupt_payment(self):
        """예전 동작(interrupt_payment) 회귀 방지."""
        state = make_state(intent="cancel", stage="payment_processing", confidence=0.9, needs_clarification=False)
        assert route(state) != "interrupt_payment"


# ══════════════════════════════════════════════
# 3. webview_tool 취소 이벤트 메커니즘
# ══════════════════════════════════════════════

class TestWebviewCancelMechanism:
    def setup_method(self):
        from src.tools.webview_tool import _clear_cancel
        _clear_cancel()

    def test_request_cancel_sets_event(self):
        from src.tools import webview_tool
        webview_tool.request_cancel()
        assert webview_tool._cancel_event.is_set()

    def test_clear_cancel_resets_event(self):
        from src.tools import webview_tool
        webview_tool.request_cancel()
        webview_tool._clear_cancel()
        assert not webview_tool._cancel_event.is_set()

    def test_check_cancel_raises_when_set(self):
        from src.tools.webview_tool import request_cancel, _check_cancel, WebviewCancelledError
        request_cancel()
        with pytest.raises(WebviewCancelledError):
            _check_cancel()

    def test_check_cancel_no_raise_when_clear(self):
        from src.tools.webview_tool import _check_cancel, _clear_cancel
        _clear_cancel()
        _check_cancel()  # 예외 없이 통과해야 함

    def test_cancel_event_is_thread_safe(self):
        """다른 스레드에서 request_cancel()해도 메인 스레드에서 감지된다."""
        from src.tools.webview_tool import request_cancel, _check_cancel, _clear_cancel, WebviewCancelledError
        _clear_cancel()

        def cancel_from_thread():
            import time
            time.sleep(0.05)
            request_cancel()

        t = threading.Thread(target=cancel_from_thread)
        t.start()
        t.join()

        with pytest.raises(WebviewCancelledError):
            _check_cancel()


# ══════════════════════════════════════════════
# 4. payment_agent_node — webview cancelled 결과 처리
# ══════════════════════════════════════════════

class TestPaymentAgentCancelledWebview:
    """
    USE_REAL_BROWSER=false이므로 실제 webview는 실행 안 됨.
    webview_tool.run_kurly_purchase를 monkeypatch해서
    cancelled=True 반환 시 payment_agent_node가 올바른 state를 반환하는지 검증.
    """

    def _make_shopping_state(self, cart_items=None):
        state = make_state(
            stage="product_confirming",
            intent="confirm",
            selected_product=MOCK_PRODUCT,
            product_url=MOCK_PRODUCT["product_url"],
            quantity=2,
            keywords=["딸기"],
            cart_items=cart_items or [],
            pending_action={"type": "address_confirm", "message": "서울시 강남구로 보낼게요. 맞으시죠?"},
        )
        return state

    def test_cancelled_no_cart(self, monkeypatch):
        """웹뷰 취소, 장바구니 없음 → idle + 단순 취소 멘트."""
        import os
        monkeypatch.setenv("USE_REAL_BROWSER", "true")

        import src.tools.webview_tool as wt
        monkeypatch.setattr(wt, "run_kurly_purchase", lambda **kwargs: {
            "cart_added": False, "cancelled": True, "storage_state_path": None,
            "delivery_info": "", "product_url": None, "error": "user_cancelled",
        })

        # platform을 kurly로 해야 should_run_real_browser 조건 충족
        product = {**MOCK_PRODUCT, "platform": "kurly"}
        state = self._make_shopping_state(cart_items=[])
        state["selected_product"] = product

        from src.payment.node import payment_agent_node
        result = payment_agent_node(state)

        assert result["stage"] == "idle"
        assert result["intent"] is None
        assert "필요하면 언제든 말씀해주세요" in result["pending_action"]["message"]
        assert result["selected_product"] is None
        assert result["keywords"] == []

    def test_cancelled_with_existing_cart(self, monkeypatch):
        """웹뷰 취소, 이전에 담은 장바구니 있음 → idle + 장바구니 유지 안내."""
        import os
        monkeypatch.setenv("USE_REAL_BROWSER", "true")

        import src.tools.webview_tool as wt
        monkeypatch.setattr(wt, "run_kurly_purchase", lambda **kwargs: {
            "cart_added": False, "cancelled": True, "storage_state_path": None,
            "delivery_info": "", "product_url": None, "error": "user_cancelled",
        })

        existing_cart = [{"product_name": "두부", "price": 3000, "quantity": 1, "total": 3000}]
        product = {**MOCK_PRODUCT, "platform": "kurly"}
        state = self._make_shopping_state(cart_items=existing_cart)
        state["selected_product"] = product

        from src.payment.node import payment_agent_node
        result = payment_agent_node(state)

        assert result["stage"] == "idle"
        assert "장바구니에 담아둔 건 그대로 있을 거에요" in result["pending_action"]["message"]

"""WON-36 — 결제 확정 후/idle 취소·환불 발화가 fallback_orchestrator 자유생성이나
쇼핑 세션 중단 문구로 새지 않고, deterministic 경계 응답으로 처리되는지 고정.

- route() 단위(LLM 없음): 가로채기 분기가 다른 모든 분기보다 먼저 걸리는지.
- 그래프 e2e(@pytest.mark.llm_smoke): 실제 실행 노드에 fallback_orchestrator/
  cancel_confirmation 이 없고, "가능"류 확답이 안 나오는지.
"""
import uuid

import pytest

from src.graph.router import route
from src.state.schema import get_default_shopping_state


def _state(user_text: str, *, stage="idle", intent=None, pending_action=None,
           confidence=0.9, needs_clarification=False, **extra) -> dict:
    st = get_default_shopping_state("user_001", "won36")
    st.update(
        stage=stage,
        intent=intent,
        confidence=confidence,
        needs_clarification=needs_clarification,
        pending_action=pending_action,
        messages=[{"role": "user", "content": user_text}],
        **extra,
    )
    return st


# ── route() 단위: 가로채기 ───────────────────────────────────────────────

@pytest.mark.parametrize("text", ["취소해줘", "이거 취소돼요?", "환불돼요?", "환불 되나요", "주문 취소하고 싶어요", "반품할래요"])
def test_route_intercepts_cancel_refund_at_idle(text):
    assert route(_state(text, intent="cancel")) == "order_action_boundary"
    assert route(_state(text, intent="ask", confidence=0.5, needs_clarification=True)) == "order_action_boundary"


def test_route_intercepts_before_entry_engagement_fallback():
    """만족도 체크인 pending 활성 중 취소·환불 발화 → fallback_orchestrator 로 안 감."""
    pending = {"type": "clarification", "message": "그때 산 딸기 어떠셨어요?",
               "payload": {"satisfaction_check": {"purchase_history_id": "x", "product_name": "딸기"}}}
    assert route(_state("환불돼요?", intent="ask", pending_action=pending)) == "order_action_boundary"


def test_route_intercepts_before_cancel_confirmation():
    """idle 에서 '취소해줘'(intent=cancel) → cancel_confirmation 대신 경계 노드."""
    assert route(_state("취소해줘", intent="cancel")) == "order_action_boundary"


# ── route() 단위: 오탐 방지 ─────────────────────────────────────────────

def test_route_does_not_intercept_shopping_cancel_confirm_answer():
    """쇼핑 세션 중단 확인('정말 중단?')에 답하는 '취소/네'는 그대로 cancel 로."""
    pending = {"type": "cancel_confirm", "message": "쇼핑을 정말 중단하시겠어요?"}
    assert route(_state("취소", intent="cancel", pending_action=pending)) == "cancel"


def test_route_does_not_intercept_mid_flow_cancel():
    """장바구니 담는 중 'cancel'은 쇼핑 중단 흐름(cancel_confirmation) 유지."""
    assert route(_state("그만할래", stage="cart_shopping", intent="cancel",
                        pending_action={"type": "continue_shopping"})) == "cancel_confirmation"


@pytest.mark.parametrize("text,intent", [("우유 사줘", "buy"), ("딸기 얼마예요?", "ask"), ("사과랑 배 중에 뭐가 나아?", "product_decision_advice")])
def test_route_does_not_intercept_normal_utterances(text, intent):
    got = route(_state(text, intent=intent))
    assert got != "order_action_boundary"


# ── 그래프 e2e ─────────────────────────────────────────────────────────

@pytest.mark.llm_smoke
@pytest.mark.parametrize("utterance", ["취소해줘", "이거 취소돼요?", "환불돼요?"])
@pytest.mark.parametrize("with_checkin", [False, True])
def test_e2e_cancel_refund_gets_boundary_response(utterance, with_checkin):
    from dotenv import load_dotenv
    load_dotenv()
    from src.graph.builder import build_graph

    tid = f"won36-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": tid}}
    g = build_graph()
    init = get_default_shopping_state("user_001", tid)
    init["conversation_id"] = abs(hash(tid)) % 1_000_000
    init["address_text"] = "서울 강남구 테헤란로 1"
    init["order_id"] = "ORDER-XYZ123"
    if not with_checkin:
        # 선제 체크인 pending 을 안 만들도록 메시지를 미리 넣어 시작
        init["messages"] = [{"role": "user", "content": utterance}]
        g.invoke(init, cfg)
    else:
        g.invoke(init, cfg)  # entry_engagement → 만족도 체크인 pending
        g.update_state(cfg, {"messages": [{"role": "user", "content": utterance}]})

    executed = []
    for chunk in g.stream(None, cfg, stream_mode="updates"):
        executed += list(chunk.keys())

    st = g.get_state(cfg).values
    resp = ""
    for m in reversed(st.get("messages", [])):
        if isinstance(m, dict) and m.get("role") == "assistant":
            resp = m["content"]; break
        if getattr(m, "type", None) == "ai":
            resp = m.content; break

    assert "fallback_orchestrator" not in executed, (utterance, with_checkin, executed)
    assert "cancel_confirmation" not in executed, (utterance, with_checkin, executed)
    assert "order_action_boundary" in executed, (utterance, with_checkin, executed)
    # 확답성 문구가 없어야 한다
    for bad in ("가능하다", "가능합니다", "취소해드릴", "환불해드릴", "환불이 가능", "취소됐"):
        assert bad not in resp, (utterance, resp)
    # 경계 안내가 있어야 한다
    assert ("어려" in resp or "직접" in resp) and ("앱" in resp or "주문내역" in resp), (utterance, resp)

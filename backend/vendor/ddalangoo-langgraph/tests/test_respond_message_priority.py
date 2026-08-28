"""WON-24 — respond_node의 needs_clarification 응답 문구 선택 로직.

기존엔 needs_clarification=True일 때 항상 immediate_response(intent_agent가
그 턴에 만든 확인 문구)를 최우선으로 썼다. intent_agent 스스로 needs_clarification
=True로 판단한 턴은 이게 맞지만, intent_agent는 False로 판단했는데 이후
다른 노드(response_agent 등)가 사후적으로 True로 뒤집은 경우엔 intent_agent의
낡은 immediate_response가 아니라 그 노드가 실제로 만든 문구가 나가야 한다.
"""
from src.agents.nodes import respond_node
from src.state.schema import get_default_shopping_state


def _state(**kwargs):
    s = get_default_shopping_state("user_test", "sess")
    s.update(kwargs)
    return s


def test_intent_agent_own_clarification_uses_immediate_response():
    """기존 동작 보존 — intent_agent 스스로 판단한 턴은 immediate_response 그대로."""
    state = _state(
        last_agent="intent_agent",
        needs_clarification=True,
        immediate_response="어떤 걸 찾아드리면 좋을까요? 조금만 더 알려주시면 바로 도와드릴게요.",
        clarification_reason="키워드 없음",
        pending_action=None,
    )
    result = respond_node(state)
    assert result["messages"][0]["content"] == "어떤 걸 찾아드리면 좋을까요? 조금만 더 알려주시면 바로 도와드릴게요."


def test_response_agent_post_hoc_flip_uses_its_own_pending_action_message():
    """WON-24 버그 재현(수정 전 FAIL) — response_agent가 target 없어서 사후적으로
    needs_clarification을 True로 뒤집은 케이스(WON-23 Unit0 case4). intent_agent의
    낡은 immediate_response("우유와 두유 중 어떤 것이 더 건강한지 궁금하신가요?")가
    아니라 response_agent 자신의 clarification 문구가 나가야 한다."""
    state = _state(
        last_agent="response_agent",
        needs_clarification=True,
        immediate_response="우유와 두유 중 어떤 것이 더 건강한지 궁금하신가요?",  # intent_agent의 낡은 값
        clarification_reason=None,
        pending_action={"type": "clarification", "message": "어떤 상품에 대해 물어보시는 건지 먼저 알려주세요.", "payload": {}},
    )
    result = respond_node(state)
    assert result["messages"][0]["content"] == "어떤 상품에 대해 물어보시는 건지 먼저 알려주세요."


def test_reorder_agent_post_hoc_flip_no_regression():
    """reorder_agent는 사후적으로 뒤집을 때 pending_action=None으로 명시하고
    immediate_response를 자기 것으로 새로 덮어쓴다 — 기존처럼 그 값이 나가야 한다
    (clarification_reason은 내부용 디버그 문구라 사용자에게 노출되면 안 됨)."""
    state = _state(
        last_agent="reorder_agent",
        needs_clarification=True,
        immediate_response="음, 예전에 사셨던 건 그게 다예요. 어떤 상품을 찾으시는지 조금 더 자세히 말씀해주시면 제가 더 잘 찾아드릴게요!",
        clarification_reason="재구매 후보를 이미 다 보여드렸는데도 사용자가 원하는 상품을 못 찾음",
        pending_action=None,
    )
    result = respond_node(state)
    assert result["messages"][0]["content"] == (
        "음, 예전에 사셨던 건 그게 다예요. 어떤 상품을 찾으시는지 조금 더 자세히 말씀해주시면 제가 더 잘 찾아드릴게요!"
    )

"""WON-38 Unit 4 — response_agent.py 배선: 자체 주소 키워드 체크 제거 →
state["question_classification"] 조합표. (address, procedure) 는 "새 주소 말씀하시면
저장" 안내로 답하고, 이어지는 주소 발화는 WON-29의 기존 저장 경로가 처리한다.

- (address, what)      → 기존 _answer_address_question (조회)
- (address, procedure) → 신규 안내 + pending_action.type=address_confirm
- question_classification 없음/None → classify_payment_question 폴백
- _ADDRESS_KEYWORDS / _is_address_question 제거 확인
- 신규 안내 뒤 주소 발화 → mock_set_default_address 저장 경로 정상 (WON-29 회귀 방지)
"""
import pytest

import src.agents.response_agent as ra
import src.agents.nodes as nodes
import src.tools.mock_tools as mock_tools
from src.tools import db_client
from src.state.schema import get_default_shopping_state


NO_ADDR_USER = "won38u4_noaddr"


def _clean(uid=NO_ADDR_USER):
    mock_tools.MOCK_ADDRESSES.pop(str(uid), None)


def setup_function(_):
    _clean()


def teardown_function(_):
    _clean()


def _ask_state(text, qc=..., user_id="user_test", **extra):
    st = get_default_shopping_state(user_id, "won38u4")
    st.update(intent="ask", messages=[{"role": "user", "content": text}], **extra)
    if qc is not ...:
        st["question_classification"] = qc
    return st


# ── 조합표 ────────────────────────────────────────────────────────────

def test_address_what_returns_lookup_answer():
    out = ra.response_agent_node(_ask_state("등록된 주소가 뭐예요?", qc={"topic": "address", "type": "what"}))
    assert out["pending_action"]["type"] == "address_confirm"
    assert "등록된 배송지" in out["pending_action"]["message"]


def test_address_procedure_returns_save_prompt():
    out = ra.response_agent_node(_ask_state("주소는 어디서 바꿔요?", qc={"topic": "address", "type": "procedure"}))
    assert out["pending_action"]["type"] == "address_confirm"
    msg = out["pending_action"]["message"]
    assert "말씀" in msg and ("저장" in msg or "등록" in msg)
    # 조회 문구("등록된 배송지는 ~")가 아니라 절차 안내여야 한다
    assert "등록된 배송지는" not in msg


def test_non_address_ask_is_not_intercepted():
    """address 가 아니면 기존 QA/clarification 경로로 빠진다."""
    out = ra.response_agent_node(_ask_state("이 우유 유기농이에요?", qc={"topic": None, "type": None}))
    assert out["pending_action"]["type"] != "address_confirm" or "배송지" not in out["pending_action"]["message"]


# ── 방어: question_classification 없음/None → 폴백 ──────────────────────

def test_missing_qc_falls_back_to_classifier_procedure():
    st = _ask_state("주소는 어디다 적어요?")  # qc 안 넣음
    assert st["question_classification"] is None  # Unit 2 이후 기본값은 None (키는 존재)
    out = ra.response_agent_node(st)
    assert out["pending_action"]["type"] == "address_confirm"
    assert "등록된 배송지는" not in out["pending_action"]["message"]  # 절차 안내


def test_missing_qc_falls_back_to_classifier_what():
    out = ra.response_agent_node(_ask_state("등록된 배송지 알려줘", qc=None))
    assert "등록된 배송지" in out["pending_action"]["message"]


# ── 자체 키워드 상수/함수 제거 ────────────────────────────────────────

@pytest.mark.parametrize("name", ["_ADDRESS_KEYWORDS", "_is_address_question"])
def test_own_address_keyword_check_removed(name):
    assert not hasattr(ra, name), f"{name} 는 Unit 4 에서 조합표로 대체돼야 한다"


# ── 신규 안내 뒤 주소 발화 → 기존 저장 경로 (WON-29 회귀 방지) ─────────

def test_address_utterance_after_procedure_prompt_saves_via_existing_path():
    # 1) 절차 질문 → response_agent 가 address_confirm pending 을 세팅
    st1 = _ask_state("주소는 어떻게 바꿔요?", qc={"topic": "address", "type": "procedure"}, user_id=NO_ADDR_USER)
    out1 = ra.response_agent_node(st1)
    assert out1["pending_action"]["type"] == "address_confirm"

    # 2) 다음 턴: 사용자가 새 주소 발화 (intent_agent 가 address_change + address_text 로 분류).
    #    respond_node(WON-29 nodes.py:71 경로)가 db_client.save_default_address 로 잇는다.
    st2 = get_default_shopping_state(NO_ADDR_USER, "won38u4")
    st2.update(
        stage="idle",
        intent="address_change",
        address_text="서울특별시 관악구 봉천로 200",
        pending_action={"type": "address_confirm", "message": out1["pending_action"]["message"]},
    )
    nodes.respond_node(st2)

    saved = db_client.get_default_address(NO_ADDR_USER, mode="mock")
    assert saved is not None
    assert saved.get("address_line1") == "서울특별시 관악구 봉천로 200"


# ── 그래프 e2e ────────────────────────────────────────────────────────

@pytest.mark.llm_smoke
def test_e2e_procedure_then_address_saves():
    import uuid
    from dotenv import load_dotenv
    load_dotenv()
    from src.graph.builder import build_graph

    uid = "won38u4_e2e"
    mock_tools.MOCK_ADDRESSES.pop(uid, None)
    tid = f"won38u4-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": tid}}
    g = build_graph()
    init = get_default_shopping_state(uid, tid)
    init["conversation_id"] = abs(hash(tid)) % 1_000_000
    init["messages"] = [{"role": "user", "content": "배송지는 어디서 바꿔요?"}]
    g.invoke(init, cfg)
    for _ in g.stream(None, cfg, stream_mode="updates"):
        pass
    resp1 = _last_assistant(g.get_state(cfg).values)
    assert ("말씀" in resp1) and ("저장" in resp1 or "등록" in resp1), resp1

    g.update_state(cfg, {"messages": [{"role": "user", "content": "서울시 마포구 월드컵로 100으로 해주세요"}]})
    for _ in g.stream(None, cfg, stream_mode="updates"):
        pass
    saved = db_client.get_default_address(uid, mode="mock")
    assert saved is not None and "월드컵로" in (saved.get("address_line1") or ""), saved
    mock_tools.MOCK_ADDRESSES.pop(uid, None)


def _last_assistant(vals):
    for m in reversed(vals.get("messages", [])):
        if isinstance(m, dict) and m.get("role") == "assistant":
            return m["content"]
        if getattr(m, "type", None) == "ai":
            return m.content
    return ""

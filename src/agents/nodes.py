"""공통 Graph 노드: wait_for_input, respond, cancel 등."""
from src.state.schema import ShoppingState
from src.state.node_inputs import RespondNodeInput, RespondNodeUpdate, CancelNodeInput
from src.utils.agent_logger import agent_logger


def session_start_node(state: ShoppingState) -> dict:
    """새 그래프 세션의 최초 진입점. 실제 분기는 route_session_start가 맡는다."""
    return {}


def wait_for_input_node(state: ShoppingState) -> dict:
    """
    사용자 입력 대기 노드.
    interrupt_before=["wait_for_input"]로 이 지점에서 항상 멈춘다.
    """
    return {}


def reset_turn_observability_node(state: ShoppingState) -> dict:
    """매 턴 시작 시 실패 관측 필드를 초기화한다.

    intent_agent_node 진입부에 끼워 넣지 않고 전용 노드로 분리한 이유: intent_agent는
    "의도 분류"라는 단일 책임을 유지하고, 나중에 intent_agent를 거치지 않는 새 진입
    경로가 생기더라도 리셋 누락 위험이 없게 하기 위함(wait_for_input → 이 노드 →
    intent_agent 순서로 배선, docs/resilience_plan.md Phase 2 참고)."""
    return {
        "degraded_mode": False,
        "degradation_reason": None,
        "failure_stage": None,
        "ranking_mode": None,
        "source_used": None,
    }


def respond_node(state: RespondNodeInput) -> RespondNodeUpdate:
    """사용자에게 보낼 메시지 생성.

    fallback_stuck_turns: Fallback Orchestrator 트리거 카운터. needs_clarification
    분기(=정해진 재질문으로도 안 풀린 턴)를 탈 때만 +1, 그 외 모든 분기(진행이
    있었던 턴)는 0으로 리셋한다 — smalltalk의 consecutive_question_turns와 같은
    패턴. router.py의 route()가 다음 턴에 이 값을 보고 fallback_orchestrator로
    보낼지 판단한다."""
    stage = state.get("stage", "idle")
    intent = state.get("intent")
    immediate = state.get("immediate_response")
    explanation = state.get("explanation")
    pending_action = state.get("pending_action") or {}
    stuck_turns = state.get("fallback_stuck_turns") or 0

    # WON-22 Unit 7 — 대체품 제안(substitution_confirm)을 거절하면 pending_
    # action을 클리어하고 단답으로 마무리한다. intent_agent가 이미 이 경우
    # product_request를 None으로 비워뒀지만(재검색 안 함), pending_action
    # 자체는 여기서 클리어해야 이전 턴의 대체품 질문이 그대로 반복되지 않는다
    # (address_confirm deny와 동일한 패턴).
    if pending_action.get("type") == "substitution_confirm" and intent == "deny":
        msg = immediate or "네, 알겠어요! 다른 상품을 찾아드릴까요?"
        agent_logger.log_respond(msg, stage, pending_action)
        return {"messages": [{"role": "assistant", "content": msg}], "pending_action": None, "fallback_stuck_turns": 0}

    # idle에서 배송지 confirm/deny — pending_action 클리어 후 단답 응답
    # (응답 agent가 방금 address_confirm을 세팅한 경우(intent=ask)는 통과시켜 그냥 표시)
    if pending_action.get("type") == "address_confirm" and stage != "payment_processing":
        if intent == "confirm":
            msg = immediate or "네, 알겠어요!"
            agent_logger.log_respond(msg, stage, pending_action)
            return {"messages": [{"role": "assistant", "content": msg}], "pending_action": None, "fallback_stuck_turns": 0}
        elif intent in ("deny", "address_change"):
            msg = immediate or "네, 알겠어요! 새 배송지를 말씀해 주시겠어요?"
            agent_logger.log_respond(msg, stage, pending_action)
            return {"messages": [{"role": "assistant", "content": msg}], "pending_action": None, "fallback_stuck_turns": 0}

    stuck = False

    if pending_action.get("type") == "product_select" and pending_action.get("message"):
        # product_select 상태에서는 reorder_agent가 이번 턴에 방금 낸 재질문
        # (예: "번호로 다시 말씀해 주세요")이 intent_agent 단계에서 만들어진
        # needs_clarification의 일반 문구보다 항상 더 구체적이고 최신이다 —
        # 아래 needs_clarification 분기가 먼저 걸리면 그 구체적 재질문이
        # 완전히 무시된다(실측 확인, fl-2026-08-21-002). needs_clarification의
        # 전체 우선순위는 다른 흐름에 영향이 넓어 안 건드리고, 이 케이스만 좁게
        # 예외로 둔다. reorder_agent 자체가 이미 후보 재제시로 회복을 시도하는
        # 중이라 여기선 stuck으로 안 침(reorder_agent의 자체 회복이 소진되면
        # pending_action이 풀리고 stage=idle로 돌아가므로, 그 이후에도 여전히
        # 애매하면 아래 needs_clarification 분기에서 자연스럽게 잡힘).
        msg = pending_action["message"]

    elif state.get("needs_clarification"):
        msg = immediate or state.get("clarification_reason") or "죄송해요, 잘 못 들었어요. 다시 한번 말씀해 주시겠어요?"
        stuck = True

    elif stage == "product_confirming" and intent == "confirm" and not state.get("quantity"):
        # intent=confirm인데 수량이 없어서 router가 어떤 agent도 안 거치고 바로
        # 여기로 온 경우(_route_product_confirming) — pending_action["message"]는
        # product_agent/reorder_agent가 상품을 처음 보여줬을 때(직전 턴) 찍어둔
        # 값이 그대로 남아있어서, 아래 pending_action.get("message") 분기를 타면
        # 사용자의 "응"을 못 들은 것처럼 완전히 똑같은 문구가 반복된다. 수량을
        # 명시적으로 되묻는 별도 문구로 응답해야 진행되고 있다는 게 느껴진다.
        msg = "네! 몇 개 필요하세요?"

    elif pending_action.get("message"):
        msg = pending_action["message"]

    elif stage == "product_confirming":
        msg = explanation or "이 상품으로 주문할까요?"

    elif stage == "payment_processing":
        msg = immediate or "결제를 계속 진행할까요?"

    elif stage == "completed":
        msg = "주문이 완료됐어요!"

    elif stage == "failed":
        msg = state.get("error") or "죄송해요, 처리하다가 문제가 생겼어요. 잠시 후 다시 시도해 주세요."

    else:
        error = state.get("error")
        _ERROR_MESSAGES = {
            "no_candidates":        "죄송해요, 그 상품은 못 찾았어요. 다른 상품으로 다시 말씀해 주시겠어요?",
            "no_relevant_products": "죄송해요, 딱 맞는 상품을 못 찾았어요. 다른 말로 다시 한번 말씀해 주시겠어요?",
            "invalid_keywords":     "어떤 상품을 찾으시는지 조금 더 자세히 말씀해주시면 제가 더 잘 찾아드릴게요!",
            "no_more_products":     "더 보여드릴 상품이 없네요. 다른 상품을 찾아볼까요?",
        }
        msg = _ERROR_MESSAGES.get(error, immediate or "무엇을 도와드릴까요?")

    agent_logger.log_respond(msg, stage, pending_action)
    return {
        "messages": [{"role": "assistant", "content": msg}],
        "fallback_stuck_turns": stuck_turns + 1 if stuck else 0,
    }


def ask_what_to_buy_node(state: ShoppingState) -> dict:
    """장바구니 후 추가 쇼핑 의사 표현 시 새 상품 입력 대기."""
    return {
        "pending_action": {
            "type": "what_to_buy",
            "message": "무엇을 구매하실까요?",
        },
        "stage": "cart_shopping",
        "keywords": [],
        "search_results": [],
        "selected_product": None,
        "reorder_resolution": None,
        "error": None,
        "quantity": None,
        "product_url": None,
        "current_product_index": 0,
        "explanation": None,
        "highlight_specs": [],
        "scored_products": [],
        "recommended_products": [],
    }


def cancel_node(state: CancelNodeInput) -> dict:
    """모든 stage에서의 cancel 처리. state 완전 리셋."""
    cart_items = state.get("cart_items") or []
    if cart_items:
        msg = "알겠어요~ 처음으로 돌아갈게요! 장바구니에 담아둔 건 그대로 있을 거에요 :)"
    else:
        msg = "알겠어요~ 필요하면 언제든 말씀해주세요!"

    return {
        "stage": "idle",
        "intent": None,
        "error": None,
        "pending_action": {"type": "payment_confirm", "message": msg},
        "last_agent": "cancel",
        "keywords": [],
        "search_results": [],
        "scored_products": [],
        "recommended_products": [],
        "selected_product": None,
        "product_url": None,
        "explanation": None,
        "highlight_specs": [],
        "current_product_index": 0,
        "quantity": None,
        "reorder_resolution": None,
        # 취소 시 진행 중이던 결제 플로우도 무효화 — 다음 결제엔 새 키 발급.
        "payment_idempotency_key": None,
    }

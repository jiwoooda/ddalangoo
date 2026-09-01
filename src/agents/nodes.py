"""공통 Graph 노드: wait_for_input, respond, cancel 등."""
from src.state.schema import (
    ShoppingState,
    product_context_reset,
    purchase_flow_reset,
    cart_clear,
    turn_observability_reset,
)
from src.state.node_inputs import RespondNodeInput, RespondNodeUpdate, CancelNodeInput
from src.tools.mock_tools import mock_clear_cart
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
    intent_agent 순서로 배선, docs/resilience_plan.md Phase 2 참고).

    WON-37: 초기화 필드 목록은 schema.py 의 turn_observability_reset() 하나로
    통일됐다(cancel_node / 결제완료 / _recover_result / ask_what_to_buy_node 과
    같은 카테고리 함수 체계). 이 지점은 다른 카테고리와 겹치지 않는다."""
    return turn_observability_reset()


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

    if pending_action.get("type") == "cancel_declined":
        msg = pending_action["message"]
        agent_logger.log_respond(msg, stage, pending_action)
        return {
            "messages": [{"role": "assistant", "content": msg}],
            "pending_action": None,
            "fallback_stuck_turns": 0,
        }

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
            new_address_text = state.get("address_text") if intent == "address_change" else None
            if new_address_text:
                # WON-29 RC-1/RC-2 — idle에서 "배송지가 없어요, 알려주시면 저장해
                # 드릴게요"에 이어 사용자가 실제로 주소를 말한 턴. 약속만 하고
                # 저장 안 하던 걸 여기서 실제로 저장한다.
                from src.tools import db_client
                db_client.save_default_address(
                    state.get("user_id", ""),
                    {
                        "address_line1": new_address_text, "address_line2": "",
                        "recipient_name": "고객", "recipient_phone": "", "zip_code": "",
                    },
                )
                _parts = new_address_text.split()
                _short = " ".join(_parts[:3]) + "..." if len(_parts) > 3 else new_address_text
                msg = f"{_short}로 저장했어요."
            else:
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
        # WON-24 — immediate_response는 intent_agent가 그 턴에 만든 확인 문구다.
        # intent_agent 스스로 needs_clarification=True를 판단한 턴엔 이게 정확히
        # 그 상황에 맞게 다듬어진 문구라 최우선으로 쓰는 게 맞다(기존 동작 유지).
        # 하지만 intent_agent는 False로 판단했는데(그래서 immediate_response는
        # "이해했어요" 류 낡은 확인 문구로 남아있음) 이후 다른 노드(response_agent
        # 등)가 사후적으로 needs_clarification을 True로 뒤집은 경우엔, 그 낡은
        # immediate_response 대신 실제로 뒤집은 노드가 만든 문구를 먼저 써야 한다
        # (fl-… WON-23 Unit0 case4: "우유랑 두유 중 뭐가 건강해?"에 답 대신
        # intent_agent의 낡은 확인 문구가 그대로 노출되던 문제).
        if state.get("last_agent") == "intent_agent":
            msg = immediate or state.get("clarification_reason") or "죄송해요, 잘 못 들었어요. 다시 한번 말씀해 주시겠어요?"
        else:
            msg = (
                pending_action.get("message")
                or immediate
                or state.get("clarification_reason")
                or "죄송해요, 잘 못 들었어요. 다시 한번 말씀해 주시겠어요?"
            )
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
    """장바구니 후 추가 쇼핑 의사 표현 시 새 상품 입력 대기.

    WON-37: 이전 상품 탐색/구매 플로우 문맥은 카테고리 함수로 초기화하되,
    **장바구니(cart_items)는 건드리지 않는다** — "담아둔 채로 다른 상품 찾기"가
    이 노드의 목적이라 cart_clear() 를 의도적으로 쓰지 않는다.
    - product_context_reset(): 검색어·조건·후보·선택상품·플랫폼 흔적
    - purchase_flow_reset():   품목 큐·레시피·추천/재구매 해소·cart_operations 등
    그 위에 얹는 노드 고유값: stage=cart_shopping, 새 품목 입력 대기 문구.
    """
    return {
        **product_context_reset(),
        **purchase_flow_reset(),
        # ── 노드 고유값 (카테고리 기본값 위에 덮어씀) ──
        "stage": "cart_shopping",
        "error": None,
        "pending_action": {
            "type": "what_to_buy",
            "message": "무엇을 구매하실까요?",
        },
    }


def cancel_node(state: CancelNodeInput) -> dict:
    """모든 stage에서의 cancel 처리 — 상품 탐색/구매 플로우 문맥과 실제
    장바구니를 전부 초기화한다.

    WON-37: 필드를 손으로 나열하던 것을 schema.py 카테고리 함수 조합으로 대체.
    - product_context_reset(): 검색어·조건·후보·선택상품·플랫폼 흔적
    - purchase_flow_reset():   대기액션·결제 멱등키(다음 결제엔 새 키)·품목 큐·
                               레시피·추천/재구매 해소 컨텍스트·cart_operations
    - cart_clear() + mock_clear_cart(): state.cart_items + 프로세스 mock 장바구니
      (cart_clear()는 state 필드만 담당 — CART_CLEAR_REQUIRES_MOCK_CLEAR_CART
       계약대로 mock_clear_cart 를 함께 호출한다)
    그 위에 얹는 cancel 고유값: stage=idle, intent/error 클리어, cancel 안내 문구.
    """
    user_id = state.get("user_id")
    if user_id:
        mock_clear_cart(user_id)
    msg = "알겠어요. 구매를 그만하고 장바구니를 모두 비웠어요. 필요하면 언제든 다시 말씀해주세요!"

    return {
        **product_context_reset(),
        **purchase_flow_reset(),
        **cart_clear(),
        # ── cancel 고유값 (카테고리 기본값 위에 덮어씀) ──
        "stage": "idle",
        "intent": None,
        "error": None,
        "pending_action": {"type": "payment_confirm", "message": msg},
        "last_agent": "cancel",
    }


_PLATFORM_APP_NAMES = {
    "coupang": "쿠팡", "kurly": "컬리", "naver": "네이버",
    "oliveyoung": "올리브영", "musinsa": "무신사",
}


def order_action_boundary_node(state: ShoppingState) -> dict:
    """WON-36 — 주문 확정 후/idle 에서 취소·환불 요청/질문을 받았을 때.

    DDALANGOO 는 third-party(쿠팡 등) 주문의 취소·환불을 조회·실행할 수단이
    없다. LLM 자유생성(fallback_orchestrator)이 "환불 가능하다니 좋은 정보네요"
    같은 근거 없는 확답을 만들지 못하도록, route()가 이 노드로 미리 가로챈다.
    여기서는 LLM 없이 고정 안내로 마감한다(cancel_confirmation 과 달리 쇼핑
    세션 중단이 아니라 "직접 처리 불가 + 앱에서 확인" 경계 안내)."""
    platform = str((state.get("selected_product") or {}).get("platform") or "").lower()
    app = _PLATFORM_APP_NAMES.get(platform)
    where = f"{app} 앱" if app else "주문하신 쇼핑몰 앱"
    msg = (
        f"주문 취소나 환불은 제가 직접 처리해 드리기 어려워요. "
        f"{where}의 주문내역에서 확인해 주세요."
    )
    agent_logger.log(f"[order_action_boundary] 취소/환불 경계 안내 | where={where}")
    return {
        "intent": None,
        "needs_clarification": False,
        "clarification_reason": None,
        "error": None,
        "last_agent": "order_action_boundary",
        "pending_action": {"type": "order_action_boundary", "message": msg},
    }


def cancel_confirmation_node(state: ShoppingState) -> dict:
    """전체 쇼핑 취소를 확인한다. 이 노드에서는 장바구니를 변경하지 않는다."""
    if state.get("intent") == "deny":
        msg = "알겠어요. 쇼핑을 계속할게요."
        return {
            "intent": None,
            "pending_action": {"type": "cancel_declined", "message": msg},
            "last_agent": "cancel_confirmation",
        }

    msg = "쇼핑을 정말 중단하시겠어요? 중단하면 장바구니에 담긴 상품도 모두 비워져요."
    return {
        "intent": None,
        "pending_action": {"type": "cancel_confirm", "message": msg},
        "last_agent": "cancel_confirmation",
    }

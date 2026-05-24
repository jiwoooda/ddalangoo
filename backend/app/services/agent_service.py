from fastapi import HTTPException
from app.schemas.agent import AgentResponse, ShoppingRequest, MessageRequest, ConfirmRequest
from app.repositories import conversation_repository, user_repository
from app.agent import runtime, mapper, actions, recommendation_sync
from app.services import memory_tools


def _execute_tools(state: dict, user_id: int, conversation_id: int) -> None:
    """
    Memory Agent가 state["tool_calls"]에 올려둔 tool 요청을 실행한다.

    save_* 계열: fire-and-forget (DB 저장).
    search_* 계열: 결과를 LangGraph state에 다시 주입.
    """
    tool_calls = state.get("tool_calls")
    if not tool_calls:
        return

    state_patch: dict = {}

    for call in tool_calls:
        tool_name = call.get("tool", "")
        args = call.get("args") or {}

        # user_id / conversation_id는 서비스 레이어에서 보장
        args.setdefault("user_id", user_id)
        args.setdefault("conversation_id", conversation_id)

        result = memory_tools.execute_tool(tool_name, args)

        # search 계열: 결과를 state에 주입
        if tool_name in memory_tools._SEARCH_TOOLS and result.get("success"):
            state_patch["tool_results"] = state_patch.get("tool_results", {})
            state_patch["tool_results"][tool_name] = result.get("results", [])

    if state_patch:
        runtime.update_state(conversation_id, state_patch)


def _save_agent_intent(state: dict, user_id: int, conversation_id: int) -> None:
    intent = state.get("intent")
    if not intent or intent == "unclear":
        return
    messages = state.get("messages") or []
    raw_input = ""
    for msg in reversed(messages):
        role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role == "human":
            raw_input = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "") or ""
            break
    conversation_repository.create_agent_intent(
        conversation_id=conversation_id,
        user_id=user_id,
        raw_user_request=raw_input,
        intent=intent,
        keywords=state.get("keywords") or [],
        confidence=state.get("confidence") or 0.9,
        needs_clarification=state.get("needs_clarification") or False,
    )


def _sync_recommendations(state: dict, user_id: int, conversation_id: int) -> dict:
    synced = recommendation_sync.persist_and_attach_ids(
        state=state,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if synced is not state:
        synced = runtime.update_state(conversation_id, {
            "recommended_products": synced.get("recommended_products") or [],
            "selected_product": synced.get("selected_product"),
            "pending_action": synced.get("pending_action"),
        })
    return synced


def start_shopping(req: ShoppingRequest) -> AgentResponse:
    user = user_repository.get_user_by_id(req.userId)
    if not user:
        raise HTTPException(status_code=404, detail={
            "category": "USER_ERROR",
            "code": "USER_NOT_FOUND",
            "message": "사용자를 찾을 수 없습니다.",
        })

    # conversation_id 채번 (mock DB)
    conv = conversation_repository.create_conversation({
        "user_id": req.userId,
        "status": "intent_detected",
        "stage": "idle",
        "keyword": None,
    })

    state = runtime.start(
        user_id=req.userId,
        message=req.message,
        conversation_id=conv["id"],
    )
    _save_agent_intent(state, req.userId, conv["id"])
    _execute_tools(state, req.userId, conv["id"])
    state = _sync_recommendations(state, req.userId, conv["id"])
    return mapper.state_to_response(state, conv["id"])


def get_conversation(conversation_id: int) -> AgentResponse:
    # 그래프 체크포인터에서 현재 상태를 꺼낸다
    graph = runtime.get_graph()
    config = runtime._config(conversation_id)
    snapshot = graph.get_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail={
            "category": "CONVERSATION_ERROR",
            "code": "CONVERSATION_NOT_FOUND",
            "message": "대화를 찾을 수 없습니다.",
        })
    return mapper.state_to_response(snapshot.values, conversation_id)


def send_message(conversation_id: int, req: MessageRequest) -> AgentResponse:
    # 그래프가 해당 conversation_id를 알고 있는지 확인
    graph = runtime.get_graph()
    config = runtime._config(conversation_id)
    snapshot = graph.get_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail={
            "category": "CONVERSATION_ERROR",
            "code": "CONVERSATION_NOT_FOUND",
            "message": "대화를 찾을 수 없습니다.",
        })

    state = runtime.resume(conversation_id=conversation_id, message=req.message)
    user_id = snapshot.values["user_id"]
    _save_agent_intent(state, user_id, conversation_id)
    _execute_tools(state, user_id, conversation_id)
    state = _sync_recommendations(state, user_id, conversation_id)
    return mapper.state_to_response(state, conversation_id)


def confirm_action(conversation_id: int, req: ConfirmRequest) -> AgentResponse:
    graph = runtime.get_graph()
    config = runtime._config(conversation_id)
    snapshot = graph.get_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail={
            "category": "CONVERSATION_ERROR",
            "code": "CONVERSATION_NOT_FOUND",
            "message": "대화를 찾을 수 없습니다.",
        })

    if req.action in ("order_now", "add_to_cart"):
        recommendation_item_id = actions.resolve_recommendation_item_id(snapshot.values, req)
        if not recommendation_item_id:
            raise HTTPException(status_code=409, detail={
                "category": "RECOMMENDATION_ERROR",
                "code": "RECOMMENDATION_ITEM_NOT_RESOLVED",
                "message": "선택된 추천 상품을 확인할 수 없어 진행할 수 없습니다.",
            })

    patch = actions.build_patch(req)
    state = runtime.inject_and_resume(conversation_id=conversation_id, patch=patch)
    state = _sync_recommendations(state, snapshot.values["user_id"], conversation_id)
    return mapper.state_to_response(state, conversation_id)

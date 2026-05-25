import os

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.agent import AgentResponse, ShoppingRequest, MessageRequest, ConfirmRequest
from app.repositories import (
    address_repository,
    agent_event_repository,
    cart_repository,
    conversation_repository,
    external_api_log_repository,
    order_repository,
    payment_repository,
    user_repository,
)
from app.agent import runtime, mapper, actions, product_data_layer, recommendation_sync
from app.services import webview_progress_service

try:
    from langchain_core.messages import AIMessage
except ImportError:  # pragma: no cover - langchain_core는 앱 런타임 의존성이다.
    AIMessage = None


async def _sync_recommendations(
    db: AsyncSession,
    state: dict,
    user_id: int,
    conversation_id: int,
) -> dict:
    synced = await recommendation_sync.persist_and_attach_ids_db(
        db=db,
        state=state,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if synced is not state:
        synced = await runtime.update_state(conversation_id, {
            "search_results": synced.get("search_results") or [],
            "recommended_products": synced.get("recommended_products") or [],
            "selected_product": synced.get("selected_product"),
            "pending_action": synced.get("pending_action"),
            "current_product_index": synced.get("current_product_index", 0),
            "product_url": synced.get("product_url"),
            "stage": synced.get("stage"),
            "error": synced.get("error"),
            "explanation": synced.get("explanation"),
        })
    return synced


def _cart_response(cart: dict, cart_item: dict | None = None) -> dict:
    """프론트/디버깅 응답에 넣기 쉬운 cart 요약을 만든다."""
    response = {
        "cartId": cart["id"],
        "status": cart["status"],
        "conversationId": cart.get("conversation_id"),
    }
    if cart_item:
        response["lastCartItem"] = {
            "cartItemId": cart_item["id"],
            "recommendationItemId": cart_item.get("recommendation_item_id"),
            "productId": cart_item["product_id"],
            "productName": cart_item["product_name_snapshot"],
            "optionText": cart_item.get("option_snapshot"),
            "quantity": cart_item["quantity"],
            "unitPrice": cart_item["unit_price_snapshot"],
        }
    return response


def _order_response(order: dict, order_items: list[dict]) -> dict:
    """DB 주문 dict를 AgentResponse.order에 넣을 형태로 변환한다."""
    main_item = order_items[0] if order_items else {}
    return {
        "orderId": order["id"],
        "status": order["status"],
        "productName": main_item.get("product_name_snapshot"),
        "optionText": main_item.get("option_snapshot"),
        "quantity": main_item.get("quantity", 1),
        "totalPaymentAmount": order["total_payment_amount"],
        "checkoutSessionId": order.get("checkout_session_id"),
    }


def _payment_response(payment: dict) -> dict:
    """DB 결제 dict를 AgentResponse.payment에 넣을 형태로 변환한다."""
    return {
        "paymentId": payment["id"],
        "orderId": payment["order_id"],
        "paymentStatus": payment["payment_status"],
        "paymentProvider": payment["payment_provider"],
        "paymentMethod": payment.get("payment_method"),
        "paymentAmount": payment["payment_amount"],
        "paymentUrl": payment.get("payment_url"),
    }


def _payment_ready_message(order_bundle: dict) -> str:
    """주문/결제 레코드가 준비된 뒤 프론트와 TTS에 내려줄 문장을 만든다."""
    order_items = order_bundle.get("order_items") or []
    first_item = order_items[0] if order_items else {}
    product_name = first_item.get("product_name_snapshot") or "상품"
    quantity = first_item.get("quantity") or 1
    total_amount = (order_bundle.get("order") or {}).get("total_payment_amount") or 0
    if total_amount:
        return f"'{product_name}' {quantity}개 주문 준비가 완료되었습니다. 결제를 진행해 주세요. 총 {total_amount:,}원입니다."
    return f"'{product_name}' {quantity}개 주문 준비가 완료되었습니다. 결제를 진행해 주세요."


def _assistant_message_patch(message: str) -> list:
    """LangGraph messages에 assistant 응답을 추가할 수 있는 형태로 감싼다."""
    if AIMessage is None:
        return [{"role": "assistant", "content": message}]
    return [AIMessage(content=message)]


def _intent_type_from(intent: str | None, needs_clarification: bool | None) -> str:
    """실행용 intent를 분석용 상위 분류 intent_type으로 변환한다."""
    if needs_clarification:
        return "clarification_needed"

    mapping = {
        "buy": "new_purchase",
        "reorder": "repurchase",
        "confirm": "confirmation",
        "deny": "rejection",
        "next": "next_product_request",
        "refine": "search_refinement",
        "compare_platforms": "platform_comparison",
        "quantity_change": "quantity_change",
        "address_change": "address_change",
        "option_select": "option_select",
        "ask": "product_question",
        "cancel": "cancel_request",
        "unclear": "unknown",
    }
    return mapping.get(intent or "unclear", "unknown")


def _pending_action_type_from(state: dict) -> str | None:
    """state.pending_action에서 현재 대기 중인 action type만 꺼낸다."""
    pending_action = state.get("pending_action")
    if not isinstance(pending_action, dict):
        return None
    return pending_action.get("type")


def _keywords_text(state: dict) -> str | None:
    """keywords 리스트를 SQL에서 보기 쉬운 comma-separated 문자열로 변환한다."""
    keywords = state.get("keywords") or []
    if not keywords:
        return None
    return ", ".join(str(keyword) for keyword in keywords)


def _target_product_name(state: dict) -> str | None:
    """intent 결과나 선택 상품에서 대표 상품명을 추출한다."""
    selected_product = state.get("selected_product") or {}
    if selected_product:
        return selected_product.get("product_name") or selected_product.get("name")

    keywords = state.get("keywords") or []
    if keywords:
        return str(keywords[0])
    return None


def _message_content_from_patch(patch: dict) -> str | None:
    """Confirm action patch에 들어간 HumanMessage 내용을 user 원문처럼 저장한다."""
    messages = patch.get("messages") or []
    if not messages:
        return None

    first_message = messages[0]
    if isinstance(first_message, dict):
        return first_message.get("content")
    return getattr(first_message, "content", None)


def _is_product_confirmation_accept(
    state: dict,
    pending_action_before: str | None,
) -> bool:
    """상품 추천 확인 단계에서 사용자가 수락했는지 판단한다."""
    return pending_action_before == "product_confirm" and state.get("intent") == "confirm"


def _is_payment_method_accept(
    state: dict,
    pending_action_before: str | None,
) -> bool:
    """결제수단 확인 단계에서 사용자가 수락했는지 판단한다."""
    return pending_action_before == "payment_method_confirm" and state.get("intent") == "confirm"


def _should_create_order_from_message(
    state: dict,
    pending_action_before: str | None,
) -> bool:
    """자연어 /messages 흐름에서 주문 생성 후처리를 연결해야 하는지 판단한다."""
    return (
        pending_action_before in {"payment_method_confirm", "address_confirm"}
        and state.get("intent") == "confirm"
        and not state.get("order")
        and not state.get("payment")
    )


def _selected_recommendation_item_id(state: dict) -> int | None:
    """현재 선택된 상품에서 DB recommendation_item_id를 찾는다."""
    selected = state.get("selected_product") or {}
    if not isinstance(selected, dict):
        return None
    return (
        selected.get("recommendation_item_id")
        or selected.get("recommendationItemId")
    )


def _real_browser_enabled() -> bool:
    """Railway/env에서 실제 브라우저 흐름이 켜져 있는지 확인한다."""
    return os.environ.get("USE_REAL_BROWSER", "false").lower() == "true"


def _emit_real_browser_progress(
    conversation_id: int,
    *,
    selected_product: dict,
    order_bundle: dict,
    payment_bundle: dict,
    assistant_message: str,
) -> dict:
    """
    DB 주문 준비 직후 웹뷰 진행 상태를 남긴다.

    현재 실제 브라우저 자동화는 컬리 모바일웹 도구만 있으므로,
    네이버 상품은 조용히 idle로 남기지 않고 명시적인 failed progress로 기록한다.
    """
    platform = (selected_product.get("platform") or "").lower()
    base_meta = {
        "orderId": order_bundle["order"]["id"],
        "paymentId": payment_bundle["payment"]["id"],
        "platform": platform or None,
    }

    if not _real_browser_enabled():
        return webview_progress_service.emit_progress(
            conversation_id,
            step="payment_ready",
            message=assistant_message,
            flow="payment",
            status="waiting_user_action",
            meta=base_meta,
        )

    running = webview_progress_service.emit_progress(
        conversation_id,
        step="payment_starting",
        message="결제 웹뷰를 준비하고 있어요.",
        flow="payment",
        status="running",
        meta=base_meta,
    )

    if platform and platform != "kurly":
        return webview_progress_service.emit_progress(
            conversation_id,
            step="payment_automation_unsupported",
            message="현재 이 플랫폼은 자동 웹뷰 결제를 아직 지원하지 않아요.",
            flow="payment",
            status="failed",
            meta={
                **base_meta,
                "error": "unsupported_real_browser_platform",
            },
        )

    return running


async def _persist_external_search_log(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    state: dict,
) -> None:
    """Platform Agent가 만든 search_results를 외부 검색/tool 호출 요약 로그로 저장한다."""
    if state.get("last_agent") not in {"platform_agent", "product_agent", "payment_agent"}:
        return

    search_results = state.get("search_results") or []
    selected_platform = state.get("selected_platform")
    tried_platforms = state.get("tried_platforms") or []
    provider = selected_platform or (",".join(tried_platforms) if tried_platforms else "unknown")

    await external_api_log_repository.create_external_api_log_db(
        db,
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "provider": provider,
            "api_name": "product_search",
            "request_summary": f"keywords={','.join(state.get('keywords') or [])}",
            "response_summary": f"results_count={len(search_results)}",
            "status_code": None,
            "success": not bool(state.get("error")),
            "error_message": state.get("error"),
            "latency_ms": None,
        },
    )


async def _persist_turn_logs(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    user_message: str,
    state: dict,
    stage_before: str | None,
    pending_action_before: str | None,
) -> dict:
    """
    한 사용자 턴에서 발생한 원문 메시지, intent 분석, assistant 응답을 저장한다.

    conversation_messages는 실제 대화 원문 분석용이고,
    agent_intents는 Intent Agent가 사용자를 어떻게 해석했는지 평가하기 위한 로그다.
    """
    await conversation_repository.create_conversation_message_db(
        db,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
    )

    intent = state.get("intent") or "unclear"
    needs_clarification = bool(state.get("needs_clarification"))
    agent_intent = await conversation_repository.create_agent_intent_db(
        db,
        {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "raw_user_request": user_message,
            "intent": intent,
            "intent_type": _intent_type_from(intent, needs_clarification),
            "stage": stage_before,
            "pending_action_type": pending_action_before,
            "target_category": None,
            "target_product_name": _target_product_name(state),
            "extracted_keywords": _keywords_text(state),
            "confidence": state.get("confidence"),
            "needs_clarification": needs_clarification,
            "clarification_reason": state.get("clarification_reason"),
        },
    )

    response = mapper.state_to_response(state, conversation_id)
    if response.assistantMessage:
        await conversation_repository.create_conversation_message_db(
            db,
            conversation_id=conversation_id,
            role="assistant",
            content=response.assistantMessage,
        )

    await conversation_repository.update_conversation_db(
        db,
        conversation_id,
        {
            "status": response.status,
            "stage": response.stage,
            "keyword": _keywords_text(state),
        },
    )

    return agent_intent


async def _run_post_graph_persistence(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    user_message: str,
    state: dict,
    stage_before: str | None,
    pending_action_before: str | None,
) -> dict:
    """
    LangGraph 실행 후 SQL 로그 저장과 추천 후보 동기화를 한 번에 처리한다.

    agent_intents를 먼저 저장한 뒤 그 id를 recommendations.intent_id에 연결한다.
    """
    state = await product_data_layer.hydrate_state_with_db_candidates(
        db,
        state=state,
        user_id=user_id,
    )
    candidates = state.get("recommended_products") or state.get("search_results") or []
    await agent_event_repository.create_agent_event_db(
        db,
        conversation_id=conversation_id,
        agent_name="product_data_layer",
        event_type="db_candidates_hydrated",
        input_summary={"intent": state.get("intent"), "keywords": state.get("keywords")},
        output_summary={"candidate_count": len(candidates), "source": (candidates[0].get("raw") or {}).get("source") if candidates else None},
    )
    agent_intent = await _persist_turn_logs(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        user_message=user_message,
        state=state,
        stage_before=stage_before,
        pending_action_before=pending_action_before,
    )
    await _persist_external_search_log(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        state=state,
    )
    state_with_intent = {
        **state,
        "agent_intent_id": agent_intent["id"],
        "user_confirmed_product": _is_product_confirmation_accept(
            state,
            pending_action_before,
        ),
    }
    synced = await _sync_recommendations(db, state_with_intent, user_id, conversation_id)
    rec_candidates = synced.get("recommended_products") or []
    await agent_event_repository.create_agent_event_db(
        db,
        conversation_id=conversation_id,
        agent_name="recommendation_sync",
        event_type="recommendation_synced",
        input_summary={"candidate_count": len(rec_candidates)},
        output_summary={
            "recommendation_id": synced.get("recommendation_id"),
            "item_ids": [c.get("recommendationItemId") for c in rec_candidates if c.get("recommendationItemId")],
        },
    )
    return synced


async def _persist_cart_order_payment_for_confirm(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    action: str,
    recommendation_item_id: int,
    state: dict,
) -> dict:
    """
    프론트 confirm action 이후 선택된 추천 후보를 장바구니/주문/결제 DB로 연결한다.

    add_to_cart는 cart/cart_item까지만 만들고,
    order_now는 MVP 결제 준비 상태까지 추적할 수 있도록 checkout/order/payment를 만든다.
    """
    if action not in {"add_to_cart", "order_now"}:
        return state

    try:
        cart = await cart_repository.get_or_create_active_cart_db(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        cart_item = await cart_repository.add_recommendation_item_to_cart_db(
            db,
            cart_id=cart["id"],
            recommendation_item_id=recommendation_item_id,
            quantity=state.get("quantity") or 1,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail={
            "category": "ORDER_ERROR",
            "code": "CART_ITEM_CREATE_FAILED",
            "message": str(error),
        }) from error

    await agent_event_repository.create_agent_event_db(
        db,
        conversation_id=conversation_id,
        agent_name="cart_service",
        event_type="cart_created",
        input_summary={"recommendation_item_id": recommendation_item_id, "action": action},
        output_summary={"cart_id": cart["id"], "cart_item_id": cart_item["id"]},
    )

    state_patch: dict = {
        "cart": _cart_response(cart, cart_item),
        "stage": "cart_shopping",
    }

    if action == "order_now":
        try:
            default_address = await address_repository.get_default_address_by_user_id_db(
                db,
                user_id,
            )
            order_bundle = await order_repository.create_order_from_cart_db(
                db,
                cart_id=cart["id"],
                user_id=user_id,
                conversation_id=conversation_id,
                address=default_address,
                status="payment_pending",
            )
            payment_bundle = await payment_repository.create_payment_for_order_db(
                db,
                order_id=order_bundle["order"]["id"],
                payment_provider="mock",
                payment_method="mock",
                payment_status="pending_user_action",
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail={
                "category": "ORDER_ERROR",
                "code": "ORDER_CREATE_FAILED",
                "message": str(error),
            }) from error

        await agent_event_repository.create_agent_event_db(
            db,
            conversation_id=conversation_id,
            agent_name="order_service",
            event_type="order_created",
            input_summary={"cart_id": cart["id"]},
            output_summary={"order_id": order_bundle["order"]["id"], "status": order_bundle["order"]["status"]},
        )
        await agent_event_repository.create_agent_event_db(
            db,
            conversation_id=conversation_id,
            agent_name="payment_service",
            event_type="payment_created",
            input_summary={"order_id": order_bundle["order"]["id"]},
            output_summary={"payment_id": payment_bundle["payment"]["id"], "payment_status": payment_bundle["payment"]["payment_status"]},
        )

        assistant_message = _payment_ready_message(order_bundle)
        selected_product = state.get("selected_product") or {}
        progress_payload = _emit_real_browser_progress(
            conversation_id,
            selected_product=selected_product if isinstance(selected_product, dict) else {},
            order_bundle=order_bundle,
            payment_bundle=payment_bundle,
            assistant_message=assistant_message,
        )

        state_patch.update({
            "stage": "payment_password_required",
            "messages": _assistant_message_patch(assistant_message),
            "webview_progress": progress_payload,
            "pending_action": {
                "type": "payment_confirm",
                "message": assistant_message,
                "payload": {
                    "orderId": order_bundle["order"]["id"],
                    "paymentId": payment_bundle["payment"]["id"],
                    "paymentStatus": payment_bundle["payment"]["payment_status"],
                },
            },
            "checkout_session": order_bundle["checkout_session"],
            "order": _order_response(
                order_bundle["order"],
                order_bundle["order_items"],
            ),
            "payment": _payment_response(payment_bundle["payment"]),
        })

    return await runtime.update_state(conversation_id, state_patch)


async def start_shopping(db: AsyncSession, req: ShoppingRequest) -> AgentResponse:
    user = await user_repository.get_user_by_id_db(db, req.userId)
    if not user:
        raise HTTPException(status_code=404, detail={
            "category": "USER_ERROR",
            "code": "USER_NOT_FOUND",
            "message": "사용자를 찾을 수 없습니다.",
        })

    # conversation_id를 먼저 만들어 LangGraph thread와 비즈니스 DB 로그를 연결한다.
    conv = await conversation_repository.create_conversation_db(db, {
        "user_id": req.userId,
        "status": "intent_detected",
        "stage": "idle",
        "keyword": None,
    })

    await agent_event_repository.create_agent_event_db(
        db,
        conversation_id=conv["id"],
        agent_name="shopping_flow",
        event_type="shopping_request_started",
        input_summary={"message": req.message[:200], "user_id": req.userId},
    )
    state = await runtime.start(
        user_id=req.userId,
        message=req.message,
        conversation_id=conv["id"],
    )
    state = await _run_post_graph_persistence(
        db,
        conversation_id=conv["id"],
        user_id=req.userId,
        user_message=req.message,
        state=state,
        stage_before="idle",
        pending_action_before=None,
    )
    return mapper.state_to_response(state, conv["id"])


async def get_conversation(db: AsyncSession, conversation_id: int) -> AgentResponse:
    # 그래프 체크포인터에서 현재 상태를 꺼낸다
    graph = runtime.get_graph()
    config = runtime._config(conversation_id)
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        conversation = await conversation_repository.get_conversation_by_id_db(db, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail={
                "category": "CONVERSATION_ERROR",
                "code": "CONVERSATION_NOT_FOUND",
                "message": "대화를 찾을 수 없습니다.",
            })
        return AgentResponse(
            conversationId=conversation_id,
            status=conversation["status"],
            stage=conversation["stage"],
            assistantMessage=conversation.get("summary") or "이전 대화 상태를 불러왔습니다.",
            recommendationId=None,
            recommendations=[],
            selectedProduct=None,
            pendingConfirmation=None,
            availableOptions=None,
            deliveryAddress=None,
            cart=None,
            order=None,
            payment=None,
            uiCommand=None,
            asyncStatus=None,
            error={
                "code": "LANGGRAPH_STATE_NOT_FOUND",
                "message": "비즈니스 대화 기록은 있으나 LangGraph 실행 상태는 없습니다.",
            },
        )
    await agent_event_repository.create_agent_event_db(
        db,
        conversation_id=conversation_id,
        agent_name="checkpoint",
        event_type="conversation_recovered",
        output_summary={"stage": snapshot.values.get("stage"), "intent": snapshot.values.get("intent")},
    )
    return mapper.state_to_response(snapshot.values, conversation_id)


async def send_message(db: AsyncSession, conversation_id: int, req: MessageRequest) -> AgentResponse:
    # 그래프가 해당 conversation_id를 알고 있는지 확인
    graph = runtime.get_graph()
    config = runtime._config(conversation_id)
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail={
            "category": "CONVERSATION_ERROR",
            "code": "CONVERSATION_NOT_FOUND",
            "message": "대화를 찾을 수 없습니다.",
        })

    pending_action_before = _pending_action_type_from(snapshot.values)
    state = await runtime.resume(conversation_id=conversation_id, message=req.message)
    user_id = int(snapshot.values["user_id"])
    state = await _run_post_graph_persistence(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        user_message=req.message,
        state=state,
        stage_before=snapshot.values.get("stage"),
        pending_action_before=pending_action_before,
    )
    if _should_create_order_from_message(state, pending_action_before):
        recommendation_item_id = _selected_recommendation_item_id(state)
        if recommendation_item_id is not None:
            state = await _persist_cart_order_payment_for_confirm(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                action="order_now",
                recommendation_item_id=int(recommendation_item_id),
                state=state,
            )
    return mapper.state_to_response(state, conversation_id)


async def confirm_action(db: AsyncSession, conversation_id: int, req: ConfirmRequest) -> AgentResponse:
    graph = runtime.get_graph()
    config = runtime._config(conversation_id)
    snapshot = await graph.aget_state(config)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail={
            "category": "CONVERSATION_ERROR",
            "code": "CONVERSATION_NOT_FOUND",
            "message": "대화를 찾을 수 없습니다.",
        })

    recommendation_item_id = None
    if req.action in ("order_now", "add_to_cart"):
        recommendation_item_id = actions.resolve_recommendation_item_id(snapshot.values, req)
        if recommendation_item_id is None:
            raise HTTPException(status_code=409, detail={
                "category": "RECOMMENDATION_ERROR",
                "code": "RECOMMENDATION_ITEM_NOT_RESOLVED",
                "message": "선택된 추천 상품을 확인할 수 없어 진행할 수 없습니다.",
            })

    patch = actions.build_patch(req)
    action_message = _message_content_from_patch(patch) or req.action
    state = await runtime.inject_and_resume(conversation_id=conversation_id, patch=patch)
    user_id = int(snapshot.values["user_id"])
    state = await _run_post_graph_persistence(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        user_message=action_message,
        state=state,
        stage_before=snapshot.values.get("stage"),
        pending_action_before=_pending_action_type_from(snapshot.values),
    )
    if recommendation_item_id is not None:
        state = await _persist_cart_order_payment_for_confirm(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            action=req.action,
            recommendation_item_id=int(recommendation_item_id),
            state=state,
        )
    return mapper.state_to_response(state, conversation_id)

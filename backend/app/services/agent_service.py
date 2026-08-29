import os
import re
import threading
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.agent import (
    AgentResponse,
    AutomationResultInAgent,
    AutomationResultRequest,
    AutomationTaskInAgent,
    ShoppingRequest,
    MessageRequest,
    ConfirmRequest,
)
from app.repositories import (
    address_repository,
    agent_event_repository,
    cart_repository,
    conversation_repository,
    external_api_log_repository,
    order_repository,
    payment_repository,
    product_search_execution_repository,
    recommendation_repository,
    user_repository,
)
from app.agent import runtime, mapper, actions, product_data_layer, recommendation_sync
from app.services import recommendation_scoring_service, webview_progress_service
from app.utils.product_url_contract import is_kurly_goods_url

logger = logging.getLogger(__name__)

try:
    from langchain_core.messages import AIMessage
except ImportError:  # pragma: no cover - langchain_core는 앱 런타임 의존성이다.
    AIMessage = None


@dataclass(frozen=True)
class WebViewOrderInput:
    """
    WebView 자동화 실행 계약.

    상품 식별은 product_id가 아니라 recommendation_item_id snapshot에서 만든다.
    execution_url은 첫 진입용이라 검색 URL일 수 있고, canonical_product_url은 /goods/
    상세 URL일 때만 직접 진입 및 상품 식별에 사용한다.
    """

    user_id: int
    conversation_id: int
    recommendation_item_id: int
    platform: str
    execution_url: str | None
    canonical_product_url: str | None
    target_product_name: str
    expected_price: int | None
    selected_options: dict
    quantity: int


def _response_with_automation_contract(
    response: AgentResponse,
    *,
    automation_task: AutomationTaskInAgent | None = None,
    automation_result: AutomationResultInAgent | None = None,
    ui_command: dict | None = None,
) -> AgentResponse:
    """
    AutomationTask/Result는 LangGraph ShoppingState가 아니라 backend orchestration 계약이다.

    그래서 state mapper가 만든 비즈니스 응답 위에, 이번 HTTP 응답에서만 필요한
    실행 계약 필드를 덧붙인다.
    """
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
    else:
        payload = response.dict()
    if automation_task is not None:
        payload["automationTask"] = automation_task
    if automation_result is not None:
        payload["automationResult"] = automation_result
    if ui_command is not None and payload.get("uiCommand") is None:
        payload["uiCommand"] = ui_command
    return AgentResponse(**payload)


def _state_to_agent_response(
    state: dict,
    conversation_id: int,
    *,
    ui_command: dict | None = None,
) -> AgentResponse:
    automation_task = None
    response_ui_command = ui_command
    if isinstance(state, dict):
        automation_task = state.pop("_response_automation_task", None)
        response_ui_command = state.pop("_response_ui_command", response_ui_command)
    response = mapper.state_to_response(state, conversation_id)
    if isinstance(automation_task, AutomationTaskInAgent) or response_ui_command is not None:
        return _response_with_automation_contract(
            response,
            automation_task=automation_task if isinstance(automation_task, AutomationTaskInAgent) else None,
            ui_command=response_ui_command,
        )
    return response


def _is_user_onboarded(user_id: int) -> bool:
    """
    LangGraph smalltalk_agent의 내부 완료 플래그(profile.onboarded_at)를
    backend orchestration에서 UI 명령으로 번역하기 위해 읽는다.
    """
    try:
        from src.tools import db_client

        profile = db_client.get_profile(str(user_id)) or {}
    except Exception:
        logger.exception("failed to read onboarding profile user_id=%s", user_id)
        return False
    return bool(profile.get("onboarded_at"))


def _attach_purchase_history_ui_command_if_onboarding_completed(
    state: dict,
    *,
    was_onboarded_before: bool,
    is_onboarded_after: bool,
) -> dict:
    """
    이번 턴에 smalltalk 온보딩이 막 끝난 경우에만 프론트 자동 전환 명령을 붙인다.

    profile.onboarded_at 같은 LangGraph 내부 필드를 프론트로 직접 노출하지 않고,
    UI가 이해할 수 있는 start_purchase_history_collection 명령으로 변환한다.
    """
    if was_onboarded_before or not is_onboarded_after:
        return state
    if state.get("last_agent") != "smalltalk_agent":
        return state

    mapped_state = dict(state)
    mapped_state["_response_ui_command"] = {
        "type": "start_purchase_history_collection",
        "reason": "onboarding_complete",
    }
    logger.info(
        "onboarding completed; uiCommand=start_purchase_history_collection user_id=%s",
        state.get("user_id"),
    )
    return mapped_state


def _automation_cart_added_state_patch(
    req: AutomationResultRequest,
    payload_override: dict | None = None,
) -> dict:
    """
    Android 실행 결과를 장바구니 비즈니스 상태로 번역한다.

    completed라는 문자열만 믿지 않고, runtime이 관찰한 수량이 있으면
    요청 수량과 비교한다. 관찰값이 없으면 성공 신호는 인정하되 payload에
    검증 불가 상태가 남아 다음 단계에서 더 보수적으로 처리할 수 있게 한다.
    """
    payload = dict(payload_override or req.payload or {})
    requested_quantity = payload.get("requestedQuantity")
    observed_quantity = payload.get("observedQuantity")
    verification_status = payload.get("verificationStatus")

    if (
        isinstance(requested_quantity, int)
        and isinstance(observed_quantity, int)
        and observed_quantity != requested_quantity
    ):
        return {
            "stage": "cart_shopping",
            "pending_action": {
                "type": "clarification",
                "message": (
                    "장바구니에 담긴 수량이 요청과 달라요. "
                    f"요청은 {requested_quantity}개였는데 실제 확인된 수량은 {observed_quantity}개예요."
                ),
                "payload": {
                    "reason": "cart_quantity_mismatch",
                    "source": "automation_runtime",
                    "taskId": req.taskId,
                    "currentStep": req.currentStep,
                    "resultType": req.resultType,
                    "payload": payload,
                },
            },
            "error": None,
            "messages": _assistant_message_patch(
                "장바구니 수량이 요청과 달라 확인이 필요해요."
            ),
        }

    return {
        "stage": "cart_shopping",
        "pending_action": None,
        "error": None,
        "messages": _assistant_message_patch(
            "장바구니 담기 자동화가 완료되었어요."
            if verification_status != "unverified"
            else "장바구니 담기는 완료됐지만 수량 확인은 하지 못했어요."
        ),
    }


def _cart_added_business_outcome(payload: dict) -> dict:
    """
    add_to_cart 실행 결과 payload에 백엔드 관점의 검증 상태를 덧붙인다.

    - matched: 요청 수량과 관찰 수량이 같음
    - mismatch: 관찰 수량이 있지만 요청과 다름
    - unverified: 장바구니 성공 신호는 있지만 실제 수량 관찰값이 없음
    """
    requested_quantity = payload.get("requestedQuantity")
    observed_quantity = payload.get("observedQuantity")

    if isinstance(requested_quantity, int) and isinstance(observed_quantity, int):
        quantity_verified = observed_quantity == requested_quantity
        return {
            "executionSucceeded": True,
            "quantityVerified": quantity_verified,
            "verificationStatus": "matched" if quantity_verified else "mismatch",
        }

    return {
        "executionSucceeded": True,
        "quantityVerified": False,
        "verificationStatus": "unverified",
    }


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
        patch: dict = {
            "search_results": synced.get("search_results") or [],
            "recommended_products": synced.get("recommended_products") or [],
            "selected_product": synced.get("selected_product"),
            "pending_action": synced.get("pending_action"),
            "current_product_index": synced.get("current_product_index", 0),
            "product_url": synced.get("product_url"),
            "stage": synced.get("stage"),
            "error": synced.get("error"),
            "explanation": synced.get("explanation"),
        }

        # selected_product가 다른 상품으로 교체됐으면 assistantMessage와 pending_action.message도 갱신.
        # 그렇지 않으면 reorder 경로에서 설정한 "스미후루..." 메시지가 남아
        # assistantMessage와 recommendations가 다른 상품을 가리키는 불일치가 생긴다.
        orig_name = (state.get("selected_product") or {}).get("product_name")
        new_product = synced.get("selected_product") or {}
        new_name = new_product.get("product_name")
        if orig_name and new_name and new_name != orig_name:
            new_price = new_product.get("price", 0)
            new_msg = f"{new_name} {new_price:,}원이에요. 주문할까요?"
            patch["messages"] = [{"role": "assistant", "content": new_msg}]
            new_pending = synced.get("pending_action")
            if isinstance(new_pending, dict):
                patch["pending_action"] = {**new_pending, "message": new_msg}

        synced = await runtime.update_state(conversation_id, patch)
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


def _is_explicit_payment_confirmation(message: str) -> bool:
    """결제는 짧은 망설임이 아니라 명시적 긍정/결제 표현에서만 진행한다."""
    compact = re.sub(r"[^\w가-힣]", "", "".join(str(message or "").split()))
    explicit_texts = {
        "응",
        "네",
        "예",
        "그래",
        "응응",
        "네네",
        "응그래",
        "응맞아",
        "네그래",
        "네맞아",
        "그래맞아",
        "좋아",
        "맞아",
        "맞아요",
        "맞습니다",
        "응맞아요",
        "네맞아요",
        "그래맞아요",
        "결제",
        "결제할래",
        "결제해줘",
        "결제할게",
        "네이버로결제",
        "네이버페이로해줘",
    }
    if compact in explicit_texts:
        return True
    return any(token in compact for token in ("결제", "네이버페이", "네이버로"))


def _is_address_confirmation_stage(state: dict, pending_action_type: str | None) -> bool:
    """배송지 확인 응답은 pending_action이 꼬여도 stage 기준으로 잡는다."""
    return state.get("stage") == "address_confirming" or pending_action_type == "address_confirm"


def _is_checkout_request(message: str) -> bool:
    """장바구니 단계에서 결제 의사가 명확한 발화인지 확인한다."""
    compact = "".join(str(message or "").split())
    return any(token in compact for token in ("결제", "계산", "구매할래", "주문할래"))


def _is_payment_password_entry(message: str) -> bool:
    """데모 결제 비밀번호 입력인지 확인한다."""
    compact = re.sub(r"\D", "", str(message or ""))
    return len(compact) == 6


def _state_order_payload(state: dict) -> dict | None:
    """state.order를 프론트 응답용 최소 order payload로 정규화한다."""
    order = state.get("order")
    if not isinstance(order, dict):
        return None
    order_id = order.get("orderId") or order.get("id")
    if not order_id:
        return order
    return {
        **order,
        "orderId": order_id,
        "status": order.get("status", "payment_pending"),
    }


def _state_payment_payload(state: dict) -> dict | None:
    """state.payment를 프론트 응답용 최소 payment payload로 정규화한다."""
    payment = state.get("payment")
    if not isinstance(payment, dict):
        return None
    payment_id = payment.get("paymentId") or payment.get("id")
    if not payment_id:
        return payment
    return {
        **payment,
        "paymentId": payment_id,
        "paymentStatus": payment.get("paymentStatus") or payment.get("payment_status") or "pending_user_action",
    }


def _kurly_cart_url() -> str:
    """컬리 장바구니/주문서 계열 WebView task의 기본 시작 URL."""
    return "https://www.kurly.com/cart"


def _state_checkout_url(state: dict, payment: dict) -> str | None:
    """state/payment 안에 저장된 장바구니/주문 관련 URL을 우선 사용한다."""
    for key in (
        "cartUrl",
        "cart_url",
        "checkoutUrl",
        "checkout_url",
        "orderUrl",
        "order_url",
    ):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("paymentUrl", "payment_url"):
        value = payment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _task_start_url(
    *,
    task: str,
    platform: str | None,
    state: dict,
    selected_product: dict,
    payment: dict,
    webview_input: WebViewOrderInput | None,
) -> str | None:
    """
    WebView task별 시작 URL을 분리한다.

    add_to_cart는 상품/검색 URL에서 시작하고, 배송지/결제 확인은 장바구니에서 시작한다.
    """
    platform_key = (platform or "").lower()
    if task in {"address_check", "payment"}:
        return _state_checkout_url(state, payment) or (
            _kurly_cart_url() if platform_key == "kurly" else None
        )

    return (
        (webview_input.canonical_product_url if webview_input else None)
        or (webview_input.execution_url if webview_input else None)
        or selected_product.get("canonical_product_url")
        or selected_product.get("product_url")
        or selected_product.get("url")
        or _state_checkout_url(state, payment)
    )


def _webview_task_payload(
    *,
    task: str,
    state: dict,
    platform: str | None = None,
    webview_input: WebViewOrderInput | None = None,
) -> dict:
    """프론트 WebView가 task별로 해석할 수 있는 표준 payload를 만든다."""
    order = _state_order_payload(state) or {}
    payment = _state_payment_payload(state) or {}
    selected_product = state.get("selected_product") if isinstance(state.get("selected_product"), dict) else {}
    platform_name = platform or (webview_input.platform if webview_input else None) or selected_product.get("platform") or "kurly"
    product_url = _task_start_url(
        task=task,
        platform=platform_name,
        state=state,
        selected_product=selected_product,
        payment=payment,
        webview_input=webview_input,
    )
    payload = {
        "task": task,
        "orderId": order.get("orderId"),
        "paymentId": payment.get("paymentId"),
        "platform": platform_name,
        "startUrl": product_url,
        "url": product_url,
    }
    if task == "add_to_cart":
        execution_url = webview_input.execution_url if webview_input else selected_product.get("execution_url")
        canonical_product_url = (
            webview_input.canonical_product_url
            if webview_input
            else selected_product.get("canonical_product_url")
        )
        payload.update({
            "productName": (
                webview_input.target_product_name
                if webview_input
                else selected_product.get("product_name") or selected_product.get("name")
            ),
            "targetProductName": (
                webview_input.target_product_name
                if webview_input
                else selected_product.get("product_name") or selected_product.get("name")
            ),
            "quantity": (
                webview_input.quantity
                if webview_input
                else state.get("quantity") or 1
            ),
            "executionUrl": execution_url,
            "canonicalProductUrl": canonical_product_url,
        })
    return payload


async def _address_required_response(conversation_id: int, state: dict) -> AgentResponse:
    """앱에 확인 가능한 배송지가 없을 때 배송지 등록 필요 상태를 반환한다."""
    message = "앱에 등록된 기본 배송지가 없어서 주문을 진행할 수 없어요. 배송지를 먼저 등록해 주세요."
    patch = {
        "stage": "address_required",
        "pending_action": {
            "type": "address_required",
            "message": message,
            "payload": {"subType": "address_required"},
        },
        "messages": _assistant_message_patch(message),
        "webview_progress": None,
    }
    state = await runtime.update_state(conversation_id, patch)
    return AgentResponse(
        conversationId=conversation_id,
        status="address_required",
        stage="address_required",
        assistantMessage=message,
        recommendationId=None,
        recommendations=[],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation={
            "type": "address",
            "message": message,
            "payload": {"subType": "address_required"},
        },
        availableOptions=None,
        deliveryAddress=state.get("delivery_address"),
        cart=state.get("cart"),
        order=_state_order_payload(state),
        payment=_state_payment_payload(state),
        uiCommand=None,
        asyncStatus=None,
        error={
            "category": "ADDRESS_ERROR",
            "code": "DEFAULT_ADDRESS_NOT_FOUND",
            "message": "앱에 등록된 기본 배송지가 없습니다.",
        },
    )


def _address_text(address: dict | None) -> str | None:
    """배송지 dict를 사용자가 확인하기 쉬운 한 줄 주소로 만든다."""
    if not isinstance(address, dict):
        return None
    line1 = address.get("address_line1") or address.get("addressLine1") or address.get("address")
    line2 = address.get("address_line2") or address.get("addressLine2")
    full_address = " ".join(str(part).strip() for part in [line1, line2] if part)
    return full_address or None


def _address_speech_text(address_text: str) -> str:
    """TTS가 주소를 붙여 읽지 않도록 음성 안내용 주소로 바꾼다."""
    text = " ".join(address_text.split())
    text = text.replace("서울특별시", "서울")
    text = text.replace("서울시", "서울")
    text = re.sub(r"([가-힣]+로)(\d+길)", r"\1 \2", text)
    text = re.sub(r"([가-힣]+동)(\d+가)", r"\1 \2", text)
    text = text.replace("(", ", ").replace(")", "")
    return text


async def _address_confirm_response(
    conversation_id: int,
    state: dict,
    delivery_address: dict,
) -> AgentResponse:
    """DB 기본 배송지를 사용해 웹뷰 없이 배송지 확인 응답을 만든다."""
    address_text = _address_text(delivery_address)
    if not address_text:
        return await _address_required_response(conversation_id, state)

    message = f"배송지는 {_address_speech_text(address_text)} 맞으세요?"
    patch = {
        "stage": "address_confirming",
        "delivery_address": delivery_address,
        "pending_action": {
            "type": "address_confirm",
            "message": message,
            "payload": {"address": delivery_address},
        },
        "messages": _assistant_message_patch(message),
        "webview_progress": None,
    }
    state = await runtime.update_state(conversation_id, patch)
    return AgentResponse(
        conversationId=conversation_id,
        status="waiting_user_confirmation",
        stage="address_confirming",
        assistantMessage=message,
        recommendationId=None,
        recommendations=[],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation={
            "type": "address",
            "message": message,
            "payload": {"address": delivery_address},
        },
        availableOptions=None,
        deliveryAddress=delivery_address,
        cart=state.get("cart"),
        order=_state_order_payload(state),
        payment=_state_payment_payload(state),
        uiCommand={"type": "close_webview"},
        asyncStatus=None,
        error=None,
    )


async def _address_required_or_default_response(
    db: AsyncSession,
    conversation_id: int,
    state: dict,
) -> AgentResponse:
    """기본 배송지를 바로 확인하고, 없으면 앱 배송지 등록 필요 상태를 반환한다."""
    try:
        user_id = int(state.get("user_id") or state.get("userId"))
    except (TypeError, ValueError):
        user_id = 0

    if user_id:
        default_address = await address_repository.get_default_address_by_user_id_db(
            db,
            user_id,
        )
        if default_address and _address_text(default_address):
            return await _address_confirm_response(
                conversation_id,
                state,
                default_address,
            )

    message = "앱에 등록된 기본 배송지가 없어서 주문을 진행할 수 없어요. 배송지를 먼저 등록해 주세요."
    patch = {
        "stage": "address_required",
        "pending_action": {
            "type": "address_required",
            "message": message,
            "payload": {"subType": "address_required"},
        },
        "messages": _assistant_message_patch(message),
        "webview_progress": None,
    }
    state = await runtime.update_state(conversation_id, patch)
    return AgentResponse(
        conversationId=conversation_id,
        status="address_required",
        stage="address_required",
        assistantMessage=message,
        recommendationId=None,
        recommendations=[],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation={
            "type": "address",
            "message": message,
            "payload": {"subType": "address_required"},
        },
        availableOptions=None,
        deliveryAddress=state.get("delivery_address"),
        cart=state.get("cart"),
        order=_state_order_payload(state),
        payment=_state_payment_payload(state),
        uiCommand=None,
        asyncStatus=None,
        error={
            "category": "ADDRESS_ERROR",
            "code": "DEFAULT_ADDRESS_NOT_FOUND",
            "message": "앱에 등록된 기본 배송지가 없습니다.",
        },
    )


def _state_has_delivery_address(state: dict) -> bool:
    """배송지 확인 수락 전에 실제 주소가 state에 있는지 검사한다."""
    address = state.get("delivery_address") or state.get("deliveryAddress")
    if not isinstance(address, dict):
        return False
    line1 = address.get("address_line1") or address.get("addressLine1") or address.get("address")
    line2 = address.get("address_line2") or address.get("addressLine2")
    return bool(" ".join(str(part).strip() for part in [line1, line2] if part).strip())


async def _address_check_retry_response(conversation_id: int, state: dict) -> AgentResponse:
    """주소가 없는 상태에서 확인 발화가 들어오면 결제로 가지 않고 중단한다."""
    message = "확인된 배송지가 없어서 결제를 진행할 수 없어요. 앱에 기본 배송지를 먼저 등록해 주세요."
    patch = {
        "stage": "address_required",
        "delivery_address": None,
        "pending_action": {
            "type": "address_required",
            "message": message,
            "payload": {"subType": "address_required"},
        },
        "messages": _assistant_message_patch(message),
        "webview_progress": None,
    }
    state = await runtime.update_state(conversation_id, patch)
    return AgentResponse(
        conversationId=conversation_id,
        status="address_required",
        stage="address_required",
        assistantMessage=message,
        recommendationId=None,
        recommendations=[],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation={
            "type": "address",
            "message": message,
            "payload": {"subType": "address_required"},
        },
        availableOptions=None,
        deliveryAddress=None,
        cart=state.get("cart"),
        order=_state_order_payload(state),
        payment=_state_payment_payload(state),
        uiCommand=None,
        asyncStatus=None,
        error={
            "category": "ADDRESS_ERROR",
            "code": "DEFAULT_ADDRESS_NOT_FOUND",
            "message": "확인된 배송지가 없어 결제를 진행할 수 없습니다.",
        },
    )


async def _payment_password_response(conversation_id: int, state: dict) -> AgentResponse:
    """배송지 확인 후 데모 결제 비밀번호 입력 단계로 넘긴다."""
    message = "네, 배송지 확인했어요. 이제 결제 비밀번호 6자리를 눌러주세요."
    patch = {
        "stage": "payment_password_required",
        "pending_action": {
            "type": "payment_password",
            "message": message,
            "payload": {
                "orderId": (state.get("order") or {}).get("orderId"),
                "paymentId": (state.get("payment") or {}).get("paymentId"),
            },
        },
        "messages": _assistant_message_patch(message),
        "webview_progress": None,
    }
    state = await runtime.update_state(conversation_id, patch)
    return AgentResponse(
        conversationId=conversation_id,
        status="payment_in_progress",
        stage="payment_password_required",
        assistantMessage=message,
        recommendationId=None,
        recommendations=[],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation={
            "type": "payment",
            "message": message,
            "payload": {
                "subType": "payment_password",
                "orderId": (state.get("order") or {}).get("orderId"),
                "paymentId": (state.get("payment") or {}).get("paymentId"),
            },
        },
        availableOptions=None,
        deliveryAddress=state.get("delivery_address"),
        cart=state.get("cart"),
        order=_state_order_payload(state),
        payment=_state_payment_payload(state),
        uiCommand=None,
        asyncStatus=None,
        error=None,
    )


async def _payment_completed_response(
    db: AsyncSession,
    conversation_id: int,
    state: dict,
) -> AgentResponse:
    """데모 결제 비밀번호 입력 후 주문 완료 응답을 만든다."""
    order_payload = _state_order_payload(state) or {}
    payment_payload = _state_payment_payload(state) or {}
    order_id = order_payload.get("orderId") or (state.get("order") or {}).get("id")
    payment_id = payment_payload.get("paymentId") or (state.get("payment") or {}).get("id")

    updated_order = None
    updated_payment = None
    if isinstance(payment_id, int):
        updated_payment = await payment_repository.update_payment_status_db(
            db,
            payment_id,
            payment_status="paid",
        )
    if isinstance(order_id, int):
        updated_order = await order_repository.update_order_status_db(
            db,
            order_id,
            status="order_completed",
        )

    order_response = (
        {"orderId": updated_order["id"], "status": updated_order["status"]}
        if updated_order
        else {**order_payload, "status": "order_completed"}
    )
    payment_response = (
        {
            "paymentId": updated_payment["id"],
            "paymentStatus": updated_payment["payment_status"],
        }
        if updated_payment
        else {**payment_payload, "paymentStatus": "paid"}
    )
    message = "결제가 완료되었어요!"
    patch = {
        "stage": "completed",
        "pending_action": None,
        "messages": _assistant_message_patch(message),
        "order": order_response,
        "payment": payment_response,
        "webview_progress": None,
    }
    state = await runtime.update_state(conversation_id, patch)
    return AgentResponse(
        conversationId=conversation_id,
        status="order_completed",
        stage="completed",
        assistantMessage=message,
        recommendationId=None,
        recommendations=[],
        selectedProduct=state.get("selected_product"),
        pendingConfirmation=None,
        availableOptions=None,
        deliveryAddress=state.get("delivery_address"),
        cart=state.get("cart"),
        order=order_response,
        payment=payment_response,
        uiCommand=None,
        asyncStatus=None,
        error=None,
    )


def _should_create_order_from_message(
    state: dict,
    pending_action_before: str | None,
    user_message: str,
) -> bool:
    """자연어 /messages 흐름에서 주문 생성 후처리를 연결해야 하는지 판단한다."""
    return (
        pending_action_before in {"payment_method_confirm", "address_confirm"}
        and state.get("intent") == "confirm"
        and (
            pending_action_before != "payment_method_confirm"
            or _is_explicit_payment_confirmation(user_message)
        )
        and not state.get("order")
        and not state.get("payment")
    )


def _should_add_cart_from_message(
    state: dict,
    pending_action_before: str | None,
) -> bool:
    """자연어 상품/수량 확인 후 DB cart에 먼저 담아야 하는지 판단한다."""
    pending_action = state.get("pending_action") or {}
    return (
        pending_action_before in {"product_confirm", "quantity_confirm"}
        and state.get("intent") == "confirm"
        and state.get("stage") == "cart_shopping"
        and pending_action.get("type") == "continue_shopping"
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


def _is_kurly_browser_product(selected_product: dict) -> bool:
    """실제 브라우저 자동화가 처리할 수 있는 컬리 상품인지 확인한다."""
    platform = (selected_product.get("platform") or "").lower()
    product_url = (selected_product.get("product_url") or selected_product.get("url") or "").lower()
    return platform == "kurly" and "kurly.com" in product_url


def _is_kurly_webview_input(webview_input: WebViewOrderInput) -> bool:
    """WebViewOrderInput 기준으로 컬리 자동화 가능 여부를 확인한다."""
    execution_url = (webview_input.execution_url or "").lower()
    canonical_url = (webview_input.canonical_product_url or "").lower()
    return (
        webview_input.platform == "kurly"
        and ("kurly.com" in execution_url or "kurly.com" in canonical_url)
    )


def _quantity_from_order_bundle(order_bundle: dict, recommendation_item_id: int) -> int:
    """주문 item 중 실행 대상 recommendation item의 수량을 찾는다."""
    for order_item in order_bundle.get("order_items") or []:
        if order_item.get("recommendation_item_id") == recommendation_item_id:
            return int(order_item.get("quantity") or 1)
    first_order_item = (order_bundle.get("order_items") or [{}])[0]
    return int(first_order_item.get("quantity") or 1)


def _first_order_recommendation_item_id(order_bundle: dict) -> int | None:
    """WebView 실행 대상은 stale selected_product가 아니라 생성된 order_items에서 고른다."""
    for order_item in order_bundle.get("order_items") or []:
        item_id = order_item.get("recommendation_item_id")
        if item_id:
            return int(item_id)
    return None


def _webview_input_from_recommendation_item(
    *,
    user_id: int,
    conversation_id: int,
    recommendation_item_id: int,
    recommendation_item: dict,
    selected_product: dict,
    order_bundle: dict,
) -> WebViewOrderInput:
    """recommendation_items snapshot을 WebView 자동화 입력으로 변환한다."""
    raw_product = selected_product.get("raw") if isinstance(selected_product.get("raw"), dict) else {}
    platform = (
        recommendation_item.get("platform")
        or selected_product.get("platform")
        or ""
    ).lower()
    execution_url = (
        recommendation_item.get("product_url")
        or selected_product.get("execution_url")
        or selected_product.get("product_url")
        or selected_product.get("url")
    )
    canonical_product_url = (
        selected_product.get("canonical_product_url")
        if is_kurly_goods_url(selected_product.get("canonical_product_url"))
        else None
    )
    if not canonical_product_url and is_kurly_goods_url(execution_url):
        canonical_product_url = execution_url

    return WebViewOrderInput(
        user_id=user_id,
        conversation_id=conversation_id,
        recommendation_item_id=recommendation_item_id,
        platform=platform,
        execution_url=execution_url,
        canonical_product_url=canonical_product_url,
        target_product_name=(
            recommendation_item.get("product_name")
            or selected_product.get("product_name")
            or selected_product.get("name")
            or raw_product.get("name")
            or "상품"
        ),
        expected_price=recommendation_item.get("price") or selected_product.get("price"),
        selected_options={},
        quantity=_quantity_from_order_bundle(order_bundle, recommendation_item_id),
    )


async def _build_webview_order_input(
    db: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
    recommendation_item_id: int,
    selected_product: dict,
    order_bundle: dict,
) -> WebViewOrderInput | None:
    """DB snapshot을 조회해서 실제 WebView 실행 입력을 만든다."""
    recommendation_item = await recommendation_repository.get_recommendation_item_by_id_db(
        db,
        recommendation_item_id,
    )
    if not recommendation_item:
        return None
    return _webview_input_from_recommendation_item(
        user_id=user_id,
        conversation_id=conversation_id,
        recommendation_item_id=recommendation_item_id,
        recommendation_item=recommendation_item,
        selected_product=selected_product,
        order_bundle=order_bundle,
    )


def _emit_real_browser_progress(
    conversation_id: int,
    *,
    selected_product: dict | None = None,
    webview_input: WebViewOrderInput | None = None,
    order_bundle: dict,
    payment_bundle: dict,
    assistant_message: str,
) -> dict:
    """
    DB 주문 준비 직후 웹뷰 진행 상태를 남긴다.

    현재 실제 브라우저 자동화는 컬리 모바일웹 도구만 있으므로,
    네이버 상품은 조용히 idle로 남기지 않고 명시적인 failed progress로 기록한다.
    """
    selected_product = selected_product or {}
    platform = (
        webview_input.platform
        if webview_input
        else (selected_product.get("platform") or "").lower()
    )
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

    return webview_progress_service.emit_progress(
        conversation_id,
        step="searching_product",
        message="컬리에서 상품을 찾고 있어요.",
        flow="payment",
        status="running",
        meta=base_meta,
    )


def _start_real_browser_purchase(
    conversation_id: int,
    *,
    selected_product: dict | None = None,
    webview_input: WebViewOrderInput | None = None,
    order_bundle: dict,
    payment_bundle: dict,
) -> None:
    """주문 확정 후 컬리 웹뷰 자동화를 백그라운드에서 시작한다."""
    selected_product = selected_product or {}
    if webview_input is None:
        raw_product = selected_product.get("raw") if isinstance(selected_product.get("raw"), dict) else {}
        fallback_url = selected_product.get("product_url") or selected_product.get("url")
        webview_input = WebViewOrderInput(
            user_id=0,
            conversation_id=conversation_id,
            recommendation_item_id=0,
            platform=(selected_product.get("platform") or "").lower(),
            execution_url=fallback_url,
            canonical_product_url=fallback_url if is_kurly_goods_url(fallback_url) else None,
            target_product_name=(
                selected_product.get("product_name")
                or selected_product.get("name")
                or raw_product.get("name")
                or "상품"
            ),
            expected_price=selected_product.get("price"),
            selected_options={},
            quantity=1,
        )
    if not _real_browser_enabled() or not _is_kurly_webview_input(webview_input):
        return

    product_name = webview_input.target_product_name
    quantity = webview_input.quantity
    reorder_url = (
        webview_input.canonical_product_url
        if is_kurly_goods_url(webview_input.canonical_product_url)
        else None
    )
    progress_flow = "reorder" if reorder_url else "new_purchase"
    base_meta = {
        "orderId": order_bundle["order"]["id"],
        "paymentId": payment_bundle["payment"]["id"],
        "platform": "kurly",
        "recommendationItemId": webview_input.recommendation_item_id,
        "executionUrl": webview_input.execution_url,
        "canonicalProductUrl": webview_input.canonical_product_url,
        "targetProductName": webview_input.target_product_name,
    }

    def run_purchase_worker() -> None:
        """Playwright 작업의 진행 상황을 프론트가 보는 webview progress로 전달한다."""
        try:
            from src.tools.webview_tool import run_kurly_purchase, get_kurly_session_path

            def progress_callback(event: dict) -> None:
                webview_progress_service.emit_progress(
                    conversation_id,
                    step=event.get("step", "webview"),
                    message=event.get("message", ""),
                    flow=event.get("flow") or progress_flow,
                    status=event.get("status", "running"),
                    screenshot_bytes=event.get("screenshot_bytes"),
                    meta=base_meta,
                )

            history_price = webview_input.expected_price if reorder_url else None
            if not isinstance(history_price, int) or history_price <= 0:
                history_price = None

            result = run_kurly_purchase(
                product_name=product_name,
                keywords=[product_name],
                quantity=int(quantity),
                storage_state_path=get_kurly_session_path(webview_input.user_id),
                reorder_url=reorder_url,
                execution_url=webview_input.execution_url,
                history_price=history_price,
                progress_callback=progress_callback,
                progress_flow=progress_flow,
            )

            if result.get("cart_added"):
                # 사용자별 세션 파일 경로를 DB에 기록한다.
                _saved_path = result.get("storage_state_path")
                if _saved_path and webview_input.user_id:
                    try:
                        import asyncio as _asyncio
                        from app.core.database import AsyncSessionLocal
                        from app.repositories.platform_session_repository import (
                            upsert_session_file_path_db,
                        )

                        async def _persist_session():
                            async with AsyncSessionLocal() as _db:
                                await upsert_session_file_path_db(
                                    _db, webview_input.user_id, _saved_path
                                )
                                await _db.commit()

                        _asyncio.run(_persist_session())
                    except Exception as _e:
                        import logging as _logging
                        _logging.getLogger(__name__).warning(
                            "[webview] 세션 경로 DB 저장 실패: %s", _e
                        )
                webview_progress_service.emit_progress(
                    conversation_id,
                    step="cart_added",
                    message="컬리 장바구니에 상품을 담았어요.",
                    flow=progress_flow,
                    status="completed",
                    meta={**base_meta, "productUrl": result.get("product_url")},
                )
                return

            if result.get("price_changed"):
                webview_progress_service.emit_progress(
                    conversation_id,
                    step="price_changed",
                    message="상품 가격이 달라져서 확인이 필요해요.",
                    flow=progress_flow,
                    status="waiting_user_confirmation",
                    meta={
                        **base_meta,
                        "currentPrice": result.get("current_price"),
                        "historyPrice": result.get("history_price"),
                    },
                )
                return

            webview_progress_service.emit_progress(
                conversation_id,
                step="webview_failed",
                message="컬리 장바구니 담기에 실패했어요.",
                flow=progress_flow,
                status="failed",
                meta={
                    **base_meta,
                    "error": result.get("error"),
                    "loginFailureReason": result.get("login_failure_reason"),
                },
            )
        except Exception as error:
            webview_progress_service.emit_progress(
                conversation_id,
                step="webview_failed",
                message="웹뷰 자동화 중 오류가 발생했어요.",
                flow=progress_flow,
                status="failed",
                meta={**base_meta, "error": str(error)},
            )

    threading.Thread(
        target=run_purchase_worker,
        daemon=True,
        name=f"kurly-webview-{conversation_id}",
    ).start()


async def _block_real_browser_unsupported_order(
    conversation_id: int,
    *,
    recommendation_item_id: int,
    state: dict,
) -> dict:
    """실제 브라우저 모드에서 컬리가 아닌 상품을 조용히 주문 생성하지 않도록 막는다."""
    selected_product = dict(state.get("selected_product") or {})
    platform = (selected_product.get("platform") or "").lower() or None
    product_url = selected_product.get("product_url") or selected_product.get("url")
    message = "현재 실제 자동 주문은 마켓컬리 상품만 지원해요. 컬리 상품으로 다시 찾아볼까요?"
    progress_payload = webview_progress_service.emit_progress(
        conversation_id,
        step="payment_automation_unsupported",
        message=message,
        flow="payment",
        status="failed",
        meta={
            "platform": platform,
            "productUrl": product_url,
            "error": "unsupported_real_browser_platform",
        },
    )
    selected_product["is_orderable"] = False
    selected_product["order_block_reason"] = "real_browser_requires_kurly"

    def mark_blocked_candidate(product: dict) -> dict:
        """선택된 추천 후보가 카드 목록에서도 주문 불가로 보이도록 동기화한다."""
        mapped = dict(product)
        candidate_id = mapped.get("recommendation_item_id") or mapped.get("recommendationItemId")
        if candidate_id == recommendation_item_id:
            mapped["is_orderable"] = False
            mapped["order_block_reason"] = "real_browser_requires_kurly"
        return mapped

    return await runtime.update_state(conversation_id, {
        "stage": "product_confirming",
        "selected_product": selected_product,
        "recommended_products": [
            mark_blocked_candidate(product)
            for product in state.get("recommended_products", [])
        ],
        "search_results": [
            mark_blocked_candidate(product)
            for product in state.get("search_results", [])
        ],
        "webview_progress": progress_payload,
        "pending_action": {
            "type": "product_confirm",
            "message": message,
            "payload": {
                "recommendationItemId": recommendation_item_id,
                "actions": ["reject"],
                "orderBlockReason": "real_browser_requires_kurly",
            },
        },
        "messages": _assistant_message_patch(message),
        "order": None,
        "payment": None,
    })



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

    selected_product = state.get("selected_product") or {}
    recommendation_item = await recommendation_repository.get_recommendation_item_by_id_db(
        db,
        recommendation_item_id,
    )
    precheck_product = recommendation_item or selected_product
    if (
        action == "order_now"
        and _real_browser_enabled()
        and not _is_kurly_browser_product(precheck_product if isinstance(precheck_product, dict) else {})
    ):
        return await _block_real_browser_unsupported_order(
            conversation_id,
            recommendation_item_id=recommendation_item_id,
            state=state,
        )

    try:
        cart = await cart_repository.get_or_create_active_cart_db(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        existing_cart_items = await cart_repository.get_cart_items_by_cart_id_db(db, cart["id"])
        should_add_item = action in {"add_to_cart", "order_now"} or not existing_cart_items
        if should_add_item:
            cart_item = await cart_repository.add_recommendation_item_to_cart_db(
                db,
                cart_id=cart["id"],
                recommendation_item_id=recommendation_item_id,
                quantity=state.get("quantity") or 1,
            )
        else:
            cart_item = existing_cart_items[-1] if existing_cart_items else None
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
        output_summary={"cart_id": cart["id"], "cart_item_id": cart_item["id"] if cart_item else None},
    )

    state_patch: dict = {
        "cart": _cart_response(cart, cart_item),
        "stage": "cart_shopping",
    }

    if action == "add_to_cart":
        product_name = (
            (cart_item or {}).get("product_name_snapshot")
            or (state.get("selected_product") or {}).get("product_name")
            or (state.get("selected_product") or {}).get("name")
            or "상품"
        )
        quantity = (cart_item or {}).get("quantity") or state.get("quantity") or 1
        state_patch.update({
            "messages": _assistant_message_patch(
                f"네, {product_name} {quantity}개를 장바구니에 담았어요. 결제할까요, 더 보실래요?"
            ),
            "pending_action": {
                "type": "payment",
                "message": "결제할까요, 더 보실래요?",
                "payload": {
                    "subType": "continue_shopping",
                    "actions": ["checkout_cart", "continue_shopping"],
                    "cartId": cart["id"],
                    "cartItemId": cart_item["id"] if cart_item else None,
                },
            },
        })
        return await runtime.update_state(conversation_id, state_patch)

    if action == "order_now":
        return await _prepare_checkout_automation_from_active_cart(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    return await runtime.update_state(conversation_id, state_patch)


async def _cart_checkout_items_for_automation(
    db: AsyncSession,
    cart_items: list[dict],
) -> list[dict]:
    """내부 cart item snapshot을 외부 앱 자동화가 실행할 item 계약으로 변환한다."""
    checkout_items: list[dict] = []
    for item in cart_items:
        recommendation_item = None
        recommendation_item_id = item.get("recommendation_item_id")
        if recommendation_item_id:
            recommendation_item = await recommendation_repository.get_recommendation_item_by_id_db(
                db,
                int(recommendation_item_id),
            )
        platform = (recommendation_item or {}).get("platform") or "kurly"
        product_name = item.get("product_name_snapshot") or (recommendation_item or {}).get("product_name") or "상품"
        checkout_items.append({
            "cartItemId": str(item["id"]),
            "recommendationItemId": recommendation_item_id,
            "platform": str(platform).lower(),
            "productName": product_name,
            "searchKeyword": product_name,
            "optionName": item.get("option_snapshot") or (recommendation_item or {}).get("option_text") or "",
            "quantity": item.get("quantity") or 1,
            "unitPrice": item.get("unit_price_snapshot"),
            "productUrl": (recommendation_item or {}).get("product_url"),
        })
    return checkout_items


def _package_name_for_platform(platform: str | None) -> str | None:
    return {
        "kurly": "com.dbs.kurly.m2",
        "coupang": "com.coupang.mobile",
    }.get((platform or "").lower())


def _product_search_task_from_execution(execution: dict) -> AutomationTaskInAgent | None:
    """DB product_search execution의 현재 플랫폼을 Android 실행 task로 변환한다."""
    platform = execution.get("current_platform")
    if not platform:
        return None
    query = execution.get("query") or ""
    search_id = execution.get("search_id") or f"{execution.get('conversation_id')}-{query}"
    return AutomationTaskInAgent(
        contractVersion=1,
        taskId=f"product-search-{search_id}-{platform}",
        taskType="product_search",
        conversationId=execution.get("conversation_id"),
        userId=execution.get("user_id"),
        platform=platform,
        packageName=_package_name_for_platform(platform),
        currentStep="open_search",
        targetProductName=query,
        searchKeyword=query,
        quantity=1,
        metadata={
            "source": "product_search_orchestrator",
            "searchId": search_id,
            "candidateLimitPerPlatform": 10,
            "platformQueue": execution.get("platform_queue") or [],
            "currentPlatformIndex": execution.get("current_platform_index") or 0,
            "preferredPlatform": execution.get("preferred_platform"),
        },
    )


def _product_search_query_from_state(state: dict) -> str | None:
    """LangGraph state에서 Android 앱 검색에 넘길 대표 검색어를 만든다."""
    search_query = str(state.get("search_query") or "").strip()
    if search_query:
        return search_query

    keywords = [
        str(keyword).strip()
        for keyword in (state.get("keywords") or [])
        if str(keyword).strip()
    ]
    if keywords:
        from src.utils.search_keywords import build_search_query

        return build_search_query(keywords) or None
    selected_product = state.get("selected_product") or {}
    product_name = selected_product.get("product_name") or selected_product.get("name")
    if product_name:
        return str(product_name).strip()
    return None


def _preferred_platform_from_state(state: dict) -> str | None:
    """LangGraph 판단 결과에 선호 플랫폼이 있으면 product_search queue의 첫 순서로 쓴다."""
    recommendation_context = state.get("recommendation_context") or {}
    preference_context = recommendation_context.get("preference_context") or {}
    preferred_platform = (
        preference_context.get("preferred_platform")
        or state.get("preferred_platform")
        or state.get("selected_platform")
    )
    return str(preferred_platform).lower().strip() if preferred_platform else None


def _product_search_fallback_decision(state: dict) -> tuple[bool, str]:
    """
    서버/MCP 후보 검색이 비었을 때 Android 앱 직접 검색으로 넘길지 판단한다.

    이전 구현처럼 error 문자열 하나에만 의존하면 Product Agent가 자연어 실패 메시지만
    만든 경우를 놓칠 수 있다. 그래서 "상품 요청인데 추천 후보가 없다"는 결과 상태를
    1순위로 보고, error는 보조 신호로만 사용한다.
    """
    query = _product_search_query_from_state(state)
    if not query:
        return False, "missing_query"

    if state.get("recommended_products") or state.get("search_results"):
        return False, "server_candidates_exist"

    selected_product = state.get("selected_product")
    if isinstance(selected_product, dict) and selected_product:
        return False, "selected_product_exists"

    pending_action = state.get("pending_action") or {}
    pending_type = pending_action.get("type") if isinstance(pending_action, dict) else None
    if pending_type == "waiting_product_search":
        return False, "already_waiting_product_search"

    stage = state.get("stage")
    if stage == "product_searching":
        return False, "already_product_searching"

    intent = state.get("intent")
    product_intents = {"buy", "reorder", "refine", "compare_platforms", "product_search"}
    product_errors = {"no_candidates", "no_relevant_products", "invalid_keywords"}
    last_agent = state.get("last_agent")
    has_product_request_signal = (
        intent in product_intents
        or state.get("error") in product_errors
        or last_agent == "product_agent"
        or (pending_type == "clarification" and bool(query))
    )
    if not has_product_request_signal:
        return False, "no_product_intent"

    return True, "start_product_search"


async def _record_product_search_result_and_next_task(
    db: AsyncSession,
    *,
    conversation_id: int,
    req: AutomationResultRequest,
    payload: dict,
) -> tuple[AutomationTaskInAgent | None, dict | None]:
    """플랫폼별 product_search 결과를 DB에 저장하고 다음 플랫폼 task를 만든다."""
    search_id = (
        payload.get("searchId")
        or req.metadata.get("searchId")
        or None
    )
    execution = None
    if search_id:
        execution = await product_search_execution_repository.get_product_search_execution_by_search_id_db(
            db,
            str(search_id),
        )
    if execution is None:
        execution = await product_search_execution_repository.get_product_search_execution_for_task_id_db(
            db,
            req.taskId,
        )
    if execution is None:
        logger.warning(
            "product search execution not found taskId=%s searchId=%s",
            req.taskId,
            search_id,
        )
        return None, None

    platform = (req.platform or payload.get("platform") or execution.get("current_platform") or "").lower()
    products = payload.get("products")
    if not isinstance(products, list):
        products = []

    updated_execution = await product_search_execution_repository.record_platform_products_db(
        db,
        search_id=execution["search_id"],
        platform=platform,
        products=[product for product in products if isinstance(product, dict)],
    )
    if updated_execution is None:
        return None, None

    next_task = _product_search_task_from_execution(updated_execution)
    logger.info(
        "productSearchResult 저장 searchId=%s platform=%s productCount=%s status=%s nextPlatform=%s",
        updated_execution["search_id"],
        platform,
        len(products),
        updated_execution["status"],
        updated_execution.get("current_platform"),
    )
    return next_task, updated_execution


async def _state_patch_from_completed_product_search(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    state: dict,
    search_execution: dict,
) -> dict:
    """수집 완료된 platformSearchProducts를 추천 후보 state로 변환한다."""
    try:
        from src.tools.meta_mcp_client import _normalize as normalize_platform_products
    except ImportError:
        normalize_platform_products = None

    raw_products = search_execution.get("merged_products") or []
    if normalize_platform_products:
        candidates = normalize_platform_products(raw_products)
    else:
        candidates = raw_products

    if not candidates:
        return {
            "stage": "idle",
            "error": "no_candidates",
            "pending_action": {
                "type": "clarification",
                "message": "쇼핑 앱에서도 상품 후보를 찾지 못했어요. 다른 상품명을 말씀해 주세요.",
            },
            "messages": _assistant_message_patch(
                "쇼핑 앱에서도 상품 후보를 찾지 못했어요. 다른 상품명을 말씀해 주세요."
            ),
        }

    ranked_candidates = await recommendation_scoring_service.rank_candidates(
        candidates,
        keywords=[str(keyword) for keyword in (state.get("keywords") or [])],
        intent=state.get("intent") or "product_search",
        condition=state.get("condition"),
        purchase_histories=(state.get("recommendation_context") or {}).get("keyword_results"),
        preference_context=(state.get("recommendation_context") or {}).get("preference_context"),
    )
    top_product = ranked_candidates[0]
    product_name = top_product.get("product_name") or top_product.get("name") or "상품"
    product_price = top_product.get("price") or 0
    hydrated_state = await recommendation_sync.persist_and_attach_ids_db(
        db,
        {
            **state,
            "stage": "searching",
            "error": None,
            "search_results": ranked_candidates,
            "recommended_products": ranked_candidates,
            "selected_product": top_product,
            "current_product_index": 0,
            "pending_action": {
                "type": "product_confirm",
                "message": f"{product_name}, {product_price:,}원이에요. 이 상품을 담을까요?",
                "payload": {
                    "actions": ["order_now", "add_to_cart", "reject"],
                    "source": "platform_product_search",
                    "searchId": search_execution.get("search_id"),
                },
            },
            "messages": _assistant_message_patch(
                f"{product_name}, {product_price:,}원이에요. 이 상품을 담을까요?"
            ),
        },
        user_id,
        conversation_id,
    )
    return {
        "stage": hydrated_state.get("stage"),
        "error": hydrated_state.get("error"),
        "search_results": hydrated_state.get("search_results") or [],
        "recommended_products": hydrated_state.get("recommended_products") or [],
        "selected_product": hydrated_state.get("selected_product"),
        "current_product_index": hydrated_state.get("current_product_index") or 0,
        "pending_action": hydrated_state.get("pending_action"),
        "messages": hydrated_state.get("messages"),
    }


async def _create_product_search_automation_task(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    query: str,
    preferred_platform: str | None = None,
    platforms: list[str] | None = None,
) -> AutomationTaskInAgent | None:
    """
    Android 앱 검색이 필요한 경우 DB execution을 만들고 첫 플랫폼 task를 반환한다.

    LangGraph는 비즈니스 판단을 담당하고, 실제 플랫폼 방문 순서와 taskId 관리는
    backend orchestration 책임으로 둔다.
    """
    query_slug = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", query).strip("-") or "search"
    existing_execution = await product_search_execution_repository.get_running_product_search_execution_db(
        db,
        conversation_id=conversation_id,
        query=query,
    )
    if existing_execution:
        task = _product_search_task_from_execution(existing_execution)
        if task:
            logger.info(
                "automationTask taskId=%s 재사용 taskType=product_search query=%s platform=%s",
                task.taskId,
                query,
                task.platform,
            )
        return task

    search_id = f"{conversation_id}-{query_slug}-{int(time.time() * 1000)}"
    execution = await product_search_execution_repository.create_product_search_execution_db(
        db,
        search_id=search_id,
        conversation_id=conversation_id,
        user_id=user_id,
        query=query,
        preferred_platform=preferred_platform,
        platforms=platforms,
    )
    task = _product_search_task_from_execution(execution)
    if task:
        logger.info(
            "automationTask taskId=%s 생성 taskType=product_search query=%s platform=%s queue=%s",
            task.taskId,
            query,
            task.platform,
            task.metadata.get("platformQueue"),
        )
    return task


async def _response_or_product_search_task(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    state: dict,
) -> AgentResponse | None:
    """서버 검색 실패 상태이면 앱 product_search task를 내려보내고 이번 턴을 종료한다."""
    query = _product_search_query_from_state(state)
    should_start, decision_reason = _product_search_fallback_decision(state)
    logger.info(
        "[ProductSearchFallback] conversationId=%s query=%s state.error=%s "
        "intent=%s stage=%s pendingType=%s recommendedCount=%s searchResultCount=%s "
        "selectedProduct=%s decision=%s reason=%s",
        conversation_id,
        query,
        state.get("error"),
        state.get("intent"),
        state.get("stage"),
        (state.get("pending_action") or {}).get("type") if isinstance(state.get("pending_action"), dict) else None,
        len(state.get("recommended_products") or []),
        len(state.get("search_results") or []),
        bool(state.get("selected_product")),
        "start" if should_start else "skip",
        decision_reason,
    )
    if not should_start:
        return None

    if not query:
        return None

    automation_task = await _create_product_search_automation_task(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        query=query,
        preferred_platform=_preferred_platform_from_state(state),
    )
    if automation_task is None:
        return None

    waiting_patch = {
        "stage": "product_searching",
        "error": None,
        "pending_action": {
            "type": "waiting_product_search",
            "message": "쇼핑 앱에서 직접 상품을 찾아볼게요.",
            "payload": {
                "query": query,
                "taskId": automation_task.taskId,
                "platform": automation_task.platform,
                "source": "product_search_orchestrator",
            },
        },
        "messages": _assistant_message_patch("쇼핑 앱에서 직접 상품을 찾아볼게요."),
    }
    updated_state = await runtime.update_state(conversation_id, waiting_patch)
    response = _state_to_agent_response(updated_state, conversation_id)
    return _response_with_automation_contract(
        response,
        automation_task=automation_task,
    )


async def _prepare_checkout_automation_from_active_cart(
    db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
) -> dict:
    """
    새 흐름의 결제 시작점.

    내부 가짜 장바구니 전체를 order/payment로 묶고, 첫 플랫폼 checkout task만 내려보낸다.
    이후 플랫폼 순차 실행은 AutomationResult 처리 단계에서 이어 붙일 예정이다.
    """
    cart = await cart_repository.get_active_cart_by_user_id_db(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    if not cart:
        raise HTTPException(status_code=409, detail={
            "category": "CART_ERROR",
            "code": "ACTIVE_CART_NOT_FOUND",
            "message": "결제할 장바구니가 없습니다.",
        })

    cart_items = await cart_repository.get_cart_items_by_cart_id_db(db, cart["id"])
    if not cart_items:
        raise HTTPException(status_code=409, detail={
            "category": "CART_ERROR",
            "code": "CART_EMPTY",
            "message": "장바구니가 비어 있습니다.",
        })

    default_address = await address_repository.get_default_address_by_user_id_db(
        db,
        user_id,
    )
    if not default_address or not _address_text(default_address):
        # WON-29 — 무주소 상태로 create_order_from_cart_db(address=None)가 실행되면
        # 빈 배송지로 주문이 생성된다. ACTIVE_CART_NOT_FOUND / CART_EMPTY 가드와
        # 같은 패턴으로 결제 시작 자체를 막는다.
        raise HTTPException(status_code=409, detail={
            "category": "ADDRESS_ERROR",
            "code": "DELIVERY_ADDRESS_REQUIRED",
            "message": "배송지를 먼저 등록해 주세요.",
        })
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
        payment_provider="internal",
        payment_method="manual",
        payment_status="pending_user_action",
    )

    checkout_items = await _cart_checkout_items_for_automation(db, cart_items)
    platforms_in_order = []
    for item in checkout_items:
        platform = item["platform"]
        if platform not in platforms_in_order:
            platforms_in_order.append(platform)

    first_platform = platforms_in_order[0] if platforms_in_order else "kurly"
    first_platform_items = [
        item for item in checkout_items if item["platform"] == first_platform
    ]
    first_item = first_platform_items[0]
    automation_task = {
        "contractVersion": 1,
        "taskId": f"checkout-{conversation_id}-{order_bundle['order']['id']}-{first_platform}",
        "taskType": "checkout_platform_cart",
        "conversationId": conversation_id,
        "userId": user_id,
        "platform": first_platform,
        "packageName": _package_name_for_platform(first_platform),
        "currentStep": "open_search",
        "targetProductName": first_item["productName"],
        "searchKeyword": first_item["searchKeyword"],
        "optionName": first_item["optionName"],
        "quantity": first_item["quantity"],
        "cartItemId": first_item["cartItemId"],
        "orderId": order_bundle["order"]["id"],
        "paymentId": payment_bundle["payment"]["id"],
        "metadata": {
            "source": "checkout_cart_flow",
            "platforms": platforms_in_order,
            "currentPlatformIndex": 0,
            "checkoutItems": checkout_items,
            "platformItems": first_platform_items,
        },
    }
    logger.info(
        "automationTask taskId=%s 생성 taskType=%s platform=%s itemCount=%s",
        automation_task["taskId"],
        automation_task["taskType"],
        first_platform,
        len(first_platform_items),
    )

    state_patch = {
        "cart": _cart_response(cart),
        "stage": "payment_processing",
        "messages": _assistant_message_patch(
            "이제 장바구니에 담긴 상품들을 실제 쇼핑 앱에 담고 결제를 진행할게요."
        ),
        "pending_action": None,
        "checkout_session": order_bundle["checkout_session"],
        "order": _order_response(
            order_bundle["order"],
            order_bundle["order_items"],
        ),
        "payment": _payment_response(payment_bundle["payment"]),
    }
    updated_state = await runtime.update_state(conversation_id, state_patch)
    updated_state["_response_automation_task"] = AutomationTaskInAgent(**automation_task)
    return updated_state


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
    was_onboarded_before = _is_user_onboarded(req.userId)
    state = await runtime.start(
        user_id=req.userId,
        message=req.message,
        conversation_id=conv["id"],
    )
    state = _attach_purchase_history_ui_command_if_onboarding_completed(
        state,
        was_onboarded_before=was_onboarded_before,
        is_onboarded_after=_is_user_onboarded(req.userId),
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
    product_search_response = await _response_or_product_search_task(
        db,
        conversation_id=conv["id"],
        user_id=req.userId,
        state=state,
    )
    if product_search_response is not None:
        return product_search_response
    return _state_to_agent_response(state, conv["id"])


async def handle_automation_result(
    db: AsyncSession,
    conversation_id: int,
    req: AutomationResultRequest,
) -> AgentResponse:
    """
    Android Accessibility runtime 결과를 LangGraph state에 반영한다.

    AutomationResult 자체는 Backend ↔ Flutter ↔ Android 실행 계약이다.
    LangGraph에는 raw runtime DTO를 넣지 않고, 쇼핑 Agent가 판단할 수 있는
    비즈니스 상태(stage/pending_action/error)만 반영한다.
    """
    conversation = await conversation_repository.get_conversation_by_id_db(
        db,
        conversation_id,
    )
    if not conversation:
        raise HTTPException(status_code=404, detail={
            "category": "CONVERSATION_ERROR",
            "code": "CONVERSATION_NOT_FOUND",
            "message": "대화를 찾을 수 없습니다.",
        })

    normalized_status = (
        "requires_user_action"
        if req.status == "needs_user_confirmation"
        else req.status
    )
    result_payload = dict(req.payload or {})
    result_metadata = dict(req.metadata or {})
    if normalized_status == "completed" and req.resultType == "cart_added":
        result_payload.update(_cart_added_business_outcome(result_payload))
    if normalized_status == "completed" and req.resultType == "checkout_platform_cart_completed":
        result_payload.update({
            "executionSucceeded": True,
            "checkoutAutomationCompleted": True,
        })
    if normalized_status == "completed" and req.resultType == "product_search_collected":
        next_task, search_execution = await _record_product_search_result_and_next_task(
            db,
            conversation_id=conversation_id,
            req=req,
            payload=result_payload,
        )
        if search_execution:
            result_payload.update({
                "searchId": search_execution["search_id"],
                "searchStatus": search_execution["status"],
                "mergedProductCount": len(search_execution.get("merged_products") or []),
                "platformQueue": search_execution.get("platform_queue") or [],
                "productsByPlatform": search_execution.get("products_by_platform") or {},
            })

    automation_result = {
        "contractVersion": req.contractVersion,
        "taskId": req.taskId,
        "taskType": req.taskType,
        "status": normalized_status,
        "currentStep": req.currentStep,
        "platform": req.platform,
        "packageName": req.packageName,
        "resultType": req.resultType,
        "errorCode": req.errorCode,
        "errorMessage": req.errorMessage,
        "message": req.errorMessage,
        "payload": result_payload,
        "metadata": result_metadata,
    }
    automation_result = {
        key: value
        for key, value in automation_result.items()
        if value is not None
    }

    state_patch: dict = {}
    if normalized_status == "completed":
        if req.resultType == "cart_added":
            state_patch.update(_automation_cart_added_state_patch(req, result_payload))
        elif req.resultType == "checkout_platform_cart_completed":
            item_outcomes = result_payload.get("itemOutcomes")
            completed_item_count = result_payload.get("completedItemCount")
            requested_item_count = result_payload.get("requestedItemCount")
            state_patch.update({
                "stage": "address_confirming",
                "pending_action": None,
                "error": None,
                "automation_outcome": {
                    "taskId": req.taskId,
                    "resultType": req.resultType,
                    "payload": result_payload,
                },
                "messages": _assistant_message_patch(
                    "쇼핑 앱 장바구니에 상품을 모두 담았어요. 배송지를 확인할게요."
                ),
            })
        elif req.resultType == "product_search_collected":
            current_state = (await runtime.get_graph().aget_state(runtime._config(conversation_id))).values
            if search_execution and search_execution.get("status") == "collected":
                state_patch.update(
                    await _state_patch_from_completed_product_search(
                        db,
                        conversation_id=conversation_id,
                        user_id=conversation["user_id"],
                        state=current_state,
                        search_execution=search_execution,
                    )
                )
            else:
                state_patch.update({
                    "stage": "product_searching",
                    "pending_action": None,
                    "error": None,
                    "automation_outcome": {
                        "taskId": req.taskId,
                        "resultType": req.resultType,
                        "payload": result_payload,
                    },
                    "messages": _assistant_message_patch(
                        "쇼핑 앱에서 상품 후보를 확인하고 있어요."
                    ),
                })
        else:
            state_patch["stage"] = "cart_shopping"
            state_patch["pending_action"] = None
            state_patch["error"] = None
            state_patch["messages"] = _assistant_message_patch("장바구니 담기 자동화가 완료되었어요.")
    elif normalized_status == "failed":
        state_patch["stage"] = "failed"
        state_patch["error"] = req.errorCode or "automation_failed"
        state_patch["pending_action"] = None
    elif normalized_status == "requires_user_action":
        state_patch["pending_action"] = {
            "type": "clarification",
            "message": req.errorMessage or "자동화 진행을 위해 확인이 필요해요.",
            "payload": {
                "reason": req.errorCode or "automation_requires_user_action",
                "source": "automation_runtime",
                "taskId": req.taskId,
                "currentStep": req.currentStep,
                "resultType": req.resultType,
                "payload": result_payload,
                "metadata": result_metadata,
            },
        }

    logger.info(
        "automationResult taskId=%s 수신 status=%s resultType=%s currentStep=%s",
        req.taskId,
        normalized_status,
        req.resultType,
        req.currentStep,
    )
    state = await runtime.update_state(conversation_id, state_patch)
    if normalized_status == "completed" and req.resultType == "product_search_collected":
        response = _state_to_agent_response(state, conversation_id)
        if next_task is not None:
            logger.info(
                "automationTask taskId=%s 생성 taskType=product_search platform=%s",
                next_task.taskId,
                next_task.platform,
            )
            return _response_with_automation_contract(
                response,
                automation_task=next_task,
                automation_result=AutomationResultInAgent(**automation_result),
            )
        logger.info(
            "product search queue completed searchId=%s mergedProductCount=%s",
            result_payload.get("searchId"),
            result_payload.get("mergedProductCount"),
        )
        return _response_with_automation_contract(
            response,
            automation_result=AutomationResultInAgent(**automation_result),
        )
    if normalized_status == "completed" and req.resultType == "cart_added":
        logger.info(
            "cart outcome translated taskId=%s executionSucceeded=%s "
            "quantityVerified=%s verificationStatus=%s requestedQuantity=%s observedQuantity=%s",
            req.taskId,
            result_payload.get("executionSucceeded"),
            result_payload.get("quantityVerified"),
            result_payload.get("verificationStatus"),
            result_payload.get("requestedQuantity"),
            result_payload.get("observedQuantity"),
        )
    if normalized_status == "completed" and req.resultType == "checkout_platform_cart_completed":
        logger.info(
            "checkout platform cart outcome translated taskId=%s completedItemCount=%s "
            "requestedItemCount=%s platforms=%s",
            req.taskId,
            result_payload.get("completedItemCount"),
            result_payload.get("requestedItemCount"),
            result_payload.get("platforms"),
        )
        response = await _address_required_or_default_response(db, conversation_id, state)
        return _response_with_automation_contract(
            response,
            automation_result=AutomationResultInAgent(**automation_result),
        )
    logger.info(
        "automation result business state 반영 완료 taskId=%s status=%s",
        req.taskId,
        normalized_status,
    )
    response = _state_to_agent_response(state, conversation_id)
    return _response_with_automation_contract(
        response,
        automation_result=AutomationResultInAgent(**automation_result),
    )


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
    return _state_to_agent_response(snapshot.values, conversation_id)


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
    if (
        snapshot.values.get("stage") == "cart_shopping"
        and pending_action_before == "continue_shopping"
        and _is_checkout_request(req.message)
    ):
        response = await _address_required_or_default_response(
            db,
            conversation_id,
            snapshot.values,
        )
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {"status": response.status, "stage": response.stage},
        )
        return response

    if _is_address_confirmation_stage(snapshot.values, pending_action_before) and (
        _is_explicit_payment_confirmation(req.message)
    ):
        response = await _payment_password_response(conversation_id, snapshot.values)
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {"status": response.status, "stage": response.stage},
        )
        return response

    if pending_action_before == "payment_password" and _is_payment_password_entry(req.message):
        response = await _payment_completed_response(db, conversation_id, snapshot.values)
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {"status": response.status, "stage": response.stage},
        )
        return response

    user_id = int(snapshot.values["user_id"])
    was_onboarded_before = _is_user_onboarded(user_id)
    state = await runtime.resume(conversation_id=conversation_id, message=req.message)
    state = _attach_purchase_history_ui_command_if_onboarding_completed(
        state,
        was_onboarded_before=was_onboarded_before,
        is_onboarded_after=_is_user_onboarded(user_id),
    )
    if _is_address_confirmation_stage(snapshot.values, pending_action_before) and (
        state.get("intent") == "confirm" or _is_explicit_payment_confirmation(req.message)
    ):
        payment_state = {
            **state,
            "delivery_address": state.get("delivery_address") or snapshot.values.get("delivery_address"),
            "order": state.get("order") or snapshot.values.get("order"),
            "payment": state.get("payment") or snapshot.values.get("payment"),
            "cart": state.get("cart") or snapshot.values.get("cart"),
        }
        response = await _payment_password_response(conversation_id, payment_state)
        await conversation_repository.update_conversation_db(
            db,
            conversation_id,
            {"status": response.status, "stage": response.stage},
        )
        return response

    state = await _run_post_graph_persistence(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        user_message=req.message,
        state=state,
        stage_before=snapshot.values.get("stage"),
        pending_action_before=pending_action_before,
    )
    product_search_response = await _response_or_product_search_task(
        db,
        conversation_id=conversation_id,
        user_id=user_id,
        state=state,
    )
    if product_search_response is not None:
        return product_search_response
    if _should_create_order_from_message(state, pending_action_before, req.message):
        state = await _prepare_checkout_automation_from_active_cart(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
    elif (
        pending_action_before in {"continue_shopping", "payment"}
        and _is_checkout_request(req.message)
    ):
        state = await _prepare_checkout_automation_from_active_cart(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
    elif _should_add_cart_from_message(state, pending_action_before):
        recommendation_item_id = _selected_recommendation_item_id(state)
        if recommendation_item_id is not None:
            state = await _persist_cart_order_payment_for_confirm(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                action="add_to_cart",
                recommendation_item_id=int(recommendation_item_id),
                state=state,
            )
    return _state_to_agent_response(state, conversation_id)


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
    pending_after = _pending_action_type_from(state)
    if recommendation_item_id is not None and pending_after != "quantity_confirm":
        state = await _persist_cart_order_payment_for_confirm(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            action=req.action,
            recommendation_item_id=int(recommendation_item_id),
            state=state,
        )
    elif req.action == "checkout_cart":
        state = await _prepare_checkout_automation_from_active_cart(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
    return _state_to_agent_response(state, conversation_id)

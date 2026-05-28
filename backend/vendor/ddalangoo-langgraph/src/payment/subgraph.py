"""
Payment Agent Node (Main Graph 진입점) — MVP.

결제 단계 (모두 fake, DB 저장만):
  1. cart_shopping 확인 후 진입 → 총액 + 결제수단 안내 (payment_method_confirm)
  2. 결제수단 확인 → 배송지 확인 (address_confirm)
  3. 배송지 확인 → 비밀번호 입력 요청 (payment_password)
  4. 비밀번호 입력 → 가짜 결제 완료 + 배송 메시지

USE_REAL_BROWSER=true 시 webview_tool로 장바구니 담기 먼저 실행.
"""
import asyncio
import os
import re
import sys
from src.state.schema import ShoppingState, bridge_shopping_to_payment, bridge_payment_to_shopping
from src.payment.flow import payment_flow


def _fetch_default_address(user_id) -> dict:
    """DB에서 기본 배송지 조회. 실패 시 빈 dict 반환."""
    _backend = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
    if _backend not in sys.path:
        sys.path.insert(0, _backend)

    async def _from_db(session):
        from app.repositories.address_repository import get_default_address_by_user_id_db
        return await get_default_address_by_user_id_db(session, int(user_id))

    async def _runner():
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return None
        engine = create_async_engine(database_url, pool_pre_ping=True, pool_size=1, max_overflow=0)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
        try:
            async with factory() as session:
                return await _from_db(session)
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_runner()) or {}
    except Exception:
        return {}
    finally:
        loop.close()


_KR_NUMBERS = {
    "하나": 1,
    "한": 1,
    "일": 1,
    "둘": 2,
    "두": 2,
    "셋": 3,
    "세": 3,
    "넷": 4,
    "네": 4,
    "다섯": 5,
    "오": 5,
    "여섯": 6,
    "육": 6,
    "일곱": 7,
    "칠": 7,
    "여덟": 8,
    "팔": 8,
    "아홉": 9,
    "구": 9,
    "열": 10,
    "십": 10,
}


def _save_purchase_history(
    state: ShoppingState,
    selected_product: dict,
    price: int,
    quantity: int,
    keywords: list | None = None,
) -> None:
    try:
        from app.repositories import purchase_history_repository
        user_id_raw = state.get("user_id", 0)
        kw_list = keywords if keywords is not None else (state.get("keywords") or [])
        purchase_history_repository.create_history({
            "user_id": int(user_id_raw),
            "conversation_id": state.get("conversation_id"),
            "product_id": selected_product.get("product_id"),
            "product_option_id": selected_product.get("product_option_id"),
            "product_name": selected_product.get("product_name", ""),
            "brand": selected_product.get("brand"),
            "category": selected_product.get("category"),
            "option_text": selected_product.get("option_text"),
            "selected_options": selected_product.get("selected_options") or {},
            "product_url": selected_product.get("product_url", ""),
            "price_at_purchase": price,
            "quantity": quantity,
            "total_price": price * quantity,
            "platform": selected_product.get("platform", ""),
            "keyword": kw_list[0] if kw_list else None,
            "satisfaction_score": None,
            "memo": None,
        })
    except Exception as e:
        print(f"[payment_agent] purchase history save failed: {e}")


def _coerce_positive_int(value, default: int | None = None) -> int | None:
    """LLM이 문자열로 준 숫자/한국어 수량도 결제 단계에서는 안전하게 정수로 맞춘다."""
    if value is None:
        return default
    if isinstance(value, int):
        return value if value > 0 else default

    text = str(value).strip()
    digit_match = re.search(r"\d+", text.replace(",", ""))
    if digit_match:
        parsed = int(digit_match.group())
        return parsed if parsed > 0 else default

    for token, number in sorted(_KR_NUMBERS.items(), key=lambda item: -len(item[0])):
        if token in text:
            return number

    return default


def _build_delivery_address(state: ShoppingState) -> dict:
    user_id = state.get("user_id", "")
    address_text = state.get("address_text")
    if address_text:
        return {
            "address_line1": address_text,
            "address_line2": "",
            "recipient_name": "고객",
            "recipient_phone": "",
            "zip_code": "",
        }
    return _fetch_default_address(user_id)


def _delivery_completion_msg(delivery_info: str) -> str:
    """배송 정보에서 도착 예정 멘트 생성."""
    if "샛별" in delivery_info:
        return " 내일 아침 7시 전 도착이에요."
    if "로켓" in delivery_info:
        return " 내일 도착이에요."
    if "당일" in delivery_info:
        return " 오늘 도착이에요."
    return ""


def _short_address(address_display: str) -> str:
    """긴 주소에서 핵심 부분만 추출 (TTS용)."""
    parts = address_display.split()
    if len(parts) > 3:
        return " ".join(parts[:3]) + "..."
    return address_display


def payment_agent_node(state: ShoppingState) -> dict:
    stage = state.get("stage")
    pending_type = (state.get("pending_action") or {}).get("type")

    selected_product = state.get("selected_product") or {}
    product_name = selected_product.get("product_name", "상품")
    keywords = state.get("keywords") or []
    short_name = keywords[0] if keywords else product_name
    price = _coerce_positive_int(selected_product.get("price"), default=0) or 0
    quantity = _coerce_positive_int(state.get("quantity"), default=None)
    if quantity is None:
        return {
            "stage": "product_confirming",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {
                "type": "quantity_confirm",
                "message": f"{short_name} 몇 개 사실래요?",
            },
        }

    total = price * quantity
    delivery_info = selected_product.get("delivery", "")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 상품/수량 확인 직후에는 결제수단으로 바로 가지 않고 장바구니 선택 단계로 멈춘다.
    # 실제 DB cart 저장은 FastAPI agent_service 후처리에서 recommendation_item_id 기준으로 수행한다.
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if (
        stage == "product_confirming"
        and pending_type in ("product_confirm", "quantity_confirm")
        and state.get("intent") == "confirm"
    ):
        existing_cart_items = state.get("cart_items") or []
        new_cart_item = {
            "product_name": product_name,
            "price": price,
            "quantity": quantity,
            "total": total,
            "product": selected_product,
            "keywords": state.get("keywords") or [],
        }
        new_cart_items = existing_cart_items + [new_cart_item]
        if len(new_cart_items) > 1:
            cart_msg = f"{short_name}도 담았어요! 총 {len(new_cart_items)}가지예요. 결제할까요, 더 담을까요?"
        else:
            cart_msg = f"{short_name} {quantity}개 담았어요! 결제할까요, 다른 것도 보실래요?"

        return {
            "stage": "cart_shopping",
            "selected_product": selected_product,
            "cart_items": new_cart_items,
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {
                "type": "continue_shopping",
                "message": cart_msg,
            },
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # USE_REAL_BROWSER: 장바구니 담기 (cart_shopping/payment_processing 진입 전)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    intent = state.get("intent")
    use_real_browser = os.environ.get("USE_REAL_BROWSER", "false").lower() == "true"
    selected_platform = (selected_product.get("platform") or "").lower()
    # 수량 입력 직후에는 결제수단/주소 확인이 아직 끝나지 않았다.
    # 실제 브라우저 자동화는 주소 확인까지 수락된 컬리 상품에서만 시도한다.
    should_run_real_browser = (
        use_real_browser
        and selected_platform == "kurly"
        and pending_type == "address_confirm"
        and intent == "confirm"
        and stage not in ("cart_shopping", "payment_processing")
    )
    if should_run_real_browser:
        from src.tools.webview_tool import run_kurly_purchase

        stored_url = selected_product.get("product_url", "")
        reorder_url = stored_url if "www.kurly.com/goods/" in stored_url else None
        progress_callback = None
        progress_flow = "reorder" if (intent == "reorder" or reorder_url) else "new_purchase"
        conversation_id = state.get("conversation_id")
        if conversation_id:
            try:
                from app.services.webview_progress_service import emit_progress

                def progress_callback(event: dict) -> None:
                    emit_progress(
                        int(conversation_id),
                        step=event.get("step", "webview"),
                        message=event.get("message", ""),
                        flow=event.get("flow") or progress_flow,
                        status=event.get("status", "running"),
                        screenshot_bytes=event.get("screenshot_bytes"),
                    )
            except Exception as e:
                print(f"[payment_agent] webview progress disabled: {e}")

        # ── 가격 변동 확인 수락/거절 처리 ──
        if pending_type == "price_change_confirm":
            if intent in ("deny", "cancel", "next"):
                return {
                    "stage": "idle",
                    "error": None,
                    "last_agent": "payment_agent",
                    "pending_action": None,
                }
            # confirm → 새 가격으로 selected_product·price·total 갱신 + 가격 체크 스킵
            current_price = (state.get("pending_action") or {}).get("payload", {}).get("current_price", price)
            selected_product = {**selected_product, "price": current_price}
            price = current_price
            total = price * quantity
            history_price_arg = None  # 사용자가 이미 확인 → 재체크 불필요
        else:
            # 재구매 URL 있을 때만 가격 체크 (일반 구매는 history_price 없음)
            history_price_arg = price if reorder_url else None

        from src.tools.webview_tool import get_kurly_session_path
        _session_path = state.get("storage_state_path") or get_kurly_session_path(
            state.get("user_id")
        )
        result = run_kurly_purchase(
            product_name=product_name,
            keywords=state.get("keywords"),
            quantity=quantity,
            storage_state_path=_session_path,
            reorder_url=reorder_url,
            history_price=history_price_arg,
            progress_callback=progress_callback,
            progress_flow=progress_flow,
        )

        # ── 취소 감지 ──
        if result.get("cancelled"):
            cart_items = state.get("cart_items") or []
            if cart_items:
                cancel_msg = "알겠어요~ 처음으로 돌아갈게요! 장바구니에 담아둔 건 그대로 있을 거에요 :)"
            else:
                cancel_msg = "알겠어요~ 필요하면 언제든 말씀해주세요!"
            return {
                "stage": "idle",
                "intent": None,
                "error": None,
                "pending_action": {"type": "payment_confirm", "message": cancel_msg},
                "last_agent": "payment_agent",
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
            }

        # ── 가격 변동 감지 → interrupt ──
        if result.get("price_changed"):
            current_price = result["current_price"]
            history_price = result["history_price"]
            direction = "올랐어요" if current_price > history_price else "내렸어요"
            return {
                "stage": "product_confirming",
                "error": None,
                "last_agent": "payment_agent",
                "storage_state_path": result.get("storage_state_path"),
                "pending_action": {
                    "type": "price_change_confirm",
                    "message": (
                        f"{short_name} 가격이 {history_price:,}원에서 "
                        f"{current_price:,}원으로 {direction}. 그래도 살까요?"
                    ),
                    "payload": {
                        "current_price": current_price,
                        "history_price": history_price,
                    },
                },
            }

        if result.get("cart_added"):
            # 웹뷰에서 추출한 배송 정보 및 실제 URL을 selected_product에 반영
            updated_product = {**selected_product}
            webview_delivery = result.get("delivery_info", "")
            if webview_delivery:
                updated_product["delivery"] = webview_delivery
            webview_url = result.get("product_url")
            if webview_url:
                updated_product["product_url"] = webview_url

            # 장바구니 항목 누적 (구매이력 저장에 필요한 전체 상품 정보 포함)
            existing_cart_items = state.get("cart_items") or []
            new_cart_item = {
                "product_name": product_name,
                "price": price,
                "quantity": quantity,
                "total": price * quantity,
                "product": updated_product,
                "keywords": state.get("keywords") or [],  # 상품 탐색 시점의 키워드 보존
            }
            new_cart_items = existing_cart_items + [new_cart_item]

            if len(new_cart_items) > 1:
                cart_msg = f"{short_name}도 담았어요! 총 {len(new_cart_items)}가지예요. 결제할까요?"
            else:
                cart_msg = f"{short_name} 담았어요! 바로 결제할까요, 다른 것도 보실래요?"

            return {
                "stage": "cart_shopping",
                "storage_state_path": result["storage_state_path"],
                "selected_product": updated_product,
                "cart_items": new_cart_items,
                "error": None,
                "last_agent": "payment_agent",
                "pending_action": {
                    "type": "continue_shopping",
                    "message": cart_msg,
                    "payload": {"storage_state_path": result["storage_state_path"]},
                },
            }

        return {
            "stage": "failed",
            "error": result.get("error") or "webview_cart_failed",
            "last_agent": "payment_agent",
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 1: 총액 + 결제수단 확인
    # cart_shopping에서 첫 진입 또는 payment_processing인데 pending 없는 경우
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if stage == "cart_shopping" or pending_type is None:
        cart_items = state.get("cart_items") or []
        if cart_items:
            cart_total = sum(item["total"] for item in cart_items)
            items_summary = ", ".join(
                f"{(item.get('keywords') or [item.get('product_name', '상품')])[0]} {item.get('quantity', 1)}개"
                for item in cart_items
            )
            payment_msg = f"{items_summary}, 총 {cart_total:,}원이에요. 네이버로 결제할까요?"
        elif selected_product:
            payment_msg = f"{short_name} {quantity}개, {total:,}원이에요. 네이버로 결제할까요?"
        else:
            return {
                "stage": "cart_shopping",
                "error": "payment_precheck_missing_product",
                "last_agent": "payment_agent",
                "pending_action": {
                    "type": "what_to_buy",
                    "message": "상품을 아직 찾지 못했어요. 무엇을 구매하실까요?",
                },
            }
        return {
            "stage": "payment_processing",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {
                "type": "payment_method_confirm",
                "message": payment_msg,
            },
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 2: 결제수단 확인 → 배송지 안내
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if pending_type == "payment_method_confirm":
        address = _build_delivery_address(state)
        addr1 = address.get("address_line1", "")
        addr2 = address.get("address_line2", "")
        address_display = f"{addr1} {addr2}".strip() if addr2 else addr1
        return {
            "stage": "payment_processing",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {
                "type": "address_confirm",
                "message": f"{_short_address(address_display)}로 보낼게요. 맞으시죠?",
            },
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 3: 배송지 확인 → 비밀번호 요청
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if pending_type == "address_confirm":
        return {
            "stage": "payment_processing",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {
                "type": "payment_password",
                "message": "비밀번호 입력해주세요!",
            },
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Step 4: 비밀번호 입력 → 가짜 결제 완료
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if pending_type == "payment_password":
        payment_state = bridge_shopping_to_payment(state, _build_delivery_address(state))
        payment_state["address_confirmed"] = True

        result_state = payment_flow(payment_state)
        result = bridge_payment_to_shopping(result_state)

        if result.get("stage") == "completed":
            arrival_msg = _delivery_completion_msg(delivery_info)
            result["pending_action"] = {
                "type": "payment_confirm",
                "message": f"완료!{arrival_msg}" if arrival_msg else "완료! 주문이 접수됐어요.",
            }
            result["storage_state_path"] = None
            cart_items = state.get("cart_items") or []
            if cart_items:
                for item in cart_items:
                    _save_purchase_history(
                        state,
                        item.get("product") or selected_product,
                        item.get("price", 0),
                        item.get("quantity", 1),
                        keywords=item.get("keywords"),
                    )
            else:
                _save_purchase_history(state, selected_product, price, quantity)
            result["cart_items"] = []

        return result

    # fallback: 알 수 없는 pending 상태 → Step 1부터 재시작 (Step 4 이후 완료 포함)
    return {
        "stage": "payment_processing",
        "error": None,
        "last_agent": "payment_agent",
        "pending_action": {
            "type": "payment_method_confirm",
            "message": f"{short_name} {quantity}개, {total:,}원이에요. 네이버로 결제할까요?",
        },
    }

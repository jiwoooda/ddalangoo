"""
Payment Agent Node (Main Graph 진입점) — MVP.

결제 단계 (모두 fake, DB 저장만):
  1. cart_shopping 확인 후 진입 → 총액 + 결제수단 안내 (payment_method_confirm)
  2. 결제수단 확인 → 배송지 확인 (address_confirm)
  3. 배송지 확인 → 비밀번호 입력 요청 (payment_password)
  4. 비밀번호 입력 → 가짜 결제 완료 + 배송 메시지

USE_REAL_BROWSER=true 시 webview_tool로 장바구니 담기 먼저 실행.
"""
import os
import re
from src.state.schema import ShoppingState, bridge_shopping_to_payment, bridge_payment_to_shopping
from src.payment.flow import payment_flow
from src.tools.mock_tools import mock_get_default_address


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
) -> None:
    try:
        from app.repositories import purchase_history_repository
        user_id_raw = state.get("user_id", 0)
        keywords = state.get("keywords") or []
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
            "keyword": keywords[0] if keywords else None,
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
    return mock_get_default_address(user_id) or {}


def _delivery_completion_msg(delivery_info: str) -> str:
    """배송 정보에서 도착 예정 멘트 생성."""
    if "샛별" in delivery_info:
        return " 내일 아침 7시 전에 도착할거예요!"
    if "로켓" in delivery_info:
        return " 내일 도착할거예요!"
    if "당일" in delivery_info:
        return " 오늘 도착할거예요!"
    return ""


def payment_agent_node(state: ShoppingState) -> dict:
    stage = state.get("stage")
    pending_type = (state.get("pending_action") or {}).get("type")

    selected_product = state.get("selected_product") or {}
    product_name = selected_product.get("product_name", "상품")
    price = _coerce_positive_int(selected_product.get("price"), default=0) or 0
    quantity = _coerce_positive_int(state.get("quantity"), default=None)
    if quantity is None:
        return {
            "stage": "product_confirming",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {
                "type": "quantity_confirm",
                "message": f"네, {product_name}으로 구매하겠습니다. 몇 개 살까요?",
            },
        }

    total = price * quantity
    delivery_info = selected_product.get("delivery", "")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # USE_REAL_BROWSER: 장바구니 담기 (cart_shopping/payment_processing 진입 전)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    use_real_browser = os.environ.get("USE_REAL_BROWSER", "false").lower() == "true"
    if use_real_browser and stage not in ("cart_shopping", "payment_processing"):
        from src.tools.webview_tool import run_kurly_purchase

        stored_url = selected_product.get("product_url", "")
        reorder_url = stored_url if "www.kurly.com/goods/" in stored_url else None

        result = run_kurly_purchase(
            product_name=product_name,
            keywords=state.get("keywords"),
            quantity=quantity,
            storage_state_path=state.get("storage_state_path"),
            reorder_url=reorder_url,
        )

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
                "product": updated_product,  # 전체 상품 정보 보존
            }
            new_cart_items = existing_cart_items + [new_cart_item]

            return {
                "stage": "cart_shopping",
                "storage_state_path": result["storage_state_path"],
                "selected_product": updated_product,
                "cart_items": new_cart_items,
                "error": None,
                "last_agent": "payment_agent",
                "pending_action": {
                    "type": "continue_shopping",
                    "message": (
                        f"'{product_name}'을(를) 장바구니에 담았어요. "
                        "결제하시겠어요, 아니면 같은 플랫폼에서 다른 상품도 더 보시겠어요?"
                    ),
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
        if len(cart_items) > 1:
            items_text = ", ".join(
                f"'{item['product_name']}' {item['quantity']}개" for item in cart_items
            )
            cart_total = sum(item["total"] for item in cart_items)
            payment_msg = f"{items_text}, 총 {cart_total:,}원입니다! 네이버 페이로 결제하실래요?"
        else:
            payment_msg = f"'{product_name}' {quantity}개, 총 {total:,}원입니다! 네이버 페이로 결제하실래요?"
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
                "message": f"배송지 '{address_display}'로 보낼게요! 맞으시죠?",
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
                "message": "비밀번호를 입력해주세요!",
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
                "message": f"구매 완료되었습니다!{arrival_msg}",
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
            "message": (
                f"'{product_name}' {quantity}개, 총 {total:,}원입니다! "
                "네이버 페이로 결제하실래요?"
            ),
        },
    }

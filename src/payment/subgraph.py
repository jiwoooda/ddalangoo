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
from src.state.schema import ShoppingState, bridge_shopping_to_payment, bridge_payment_to_shopping
from src.payment.flow import payment_flow
from src.tools.mock_tools import mock_get_default_address


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
    price = selected_product.get("price", 0)
    quantity = state.get("quantity") or 1
    total = price * quantity
    delivery_info = selected_product.get("delivery", "")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # USE_REAL_BROWSER: 장바구니 담기 (cart_shopping/payment_processing 진입 전)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    use_real_browser = os.environ.get("USE_REAL_BROWSER", "false").lower() == "true"
    if use_real_browser and stage not in ("cart_shopping", "payment_processing"):
        from src.tools.webview_tool import run_kurly_purchase

        payment_state = bridge_shopping_to_payment(state, _build_delivery_address(state))
        result = run_kurly_purchase(
            product_name=product_name,
            keywords=state.get("keywords"),
            quantity=quantity,
            storage_state_path=state.get("storage_state_path"),
        )

        if result.get("cart_added"):
            # 웹뷰에서 추출한 배송 정보를 selected_product에 반영
            webview_delivery = result.get("delivery_info", "")
            updated_product = {**selected_product}
            if webview_delivery:
                updated_product["delivery"] = webview_delivery

            return {
                "stage": "cart_shopping",
                "storage_state_path": result["storage_state_path"],
                "selected_product": updated_product,
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

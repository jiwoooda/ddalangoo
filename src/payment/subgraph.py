"""
Payment Agent Node (Main Graph 진입점) — MVP.

- 배송지: 기저장 주소 자동 사용 (확인 생략)
- 옵션: 없음
- 결제: DB 저장만 (실제 결제 없음)
- USE_REAL_BROWSER=true 시 webview_tool 호출
"""
import os
from typing import Any, Optional
from src.state.schema import ShoppingState, bridge_shopping_to_payment, bridge_payment_to_shopping
from src.payment.flow import payment_flow
from src.tools.mock_tools import mock_get_default_address

USE_REAL_BROWSER = os.environ.get("USE_REAL_BROWSER", "false").lower() == "true"


def payment_agent_node(state: ShoppingState) -> dict:
    user_id = state.get("user_id", "")

    # 배송지: address_text 우선, 없으면 기저장 주소 자동 사용
    address_text = state.get("address_text")
    if address_text:
        delivery_address = {
            "address_line1": address_text,
            "address_line2": "",
            "recipient_name": "고객",
            "recipient_phone": "",
            "zip_code": "",
        }
    else:
        delivery_address = mock_get_default_address(user_id)

    # PaymentState 생성 (address_confirmed=True: 확인 단계 생략)
    payment_state = bridge_shopping_to_payment(state, delivery_address)
    payment_state["address_confirmed"] = True

    # 실제 브라우저 모드: webview_tool 호출
    if USE_REAL_BROWSER:
        from src.tools.webview_tool import run_kurly_purchase

        # cart_shopping에서 온 경우 = 사용자가 "결제할게요" 선택
        # → webview 없이 DB 저장만 하고 완료 처리
        if state.get("stage") == "cart_shopping":
            result_state = payment_flow(payment_state)
            return bridge_payment_to_shopping(result_state)

        result = run_kurly_purchase(
            product_url=payment_state["product_url"],
            storage_state_path=state.get("storage_state_path"),
        )

        if result.get("cart_added"):
            product_name = (payment_state.get("selected_product") or {}).get("product_name", "상품")
            return {
                "stage": "cart_shopping",
                "storage_state_path": result["storage_state_path"],
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

    # Mock 모드: payment_flow 실행
    result_state = payment_flow(payment_state)
    return bridge_payment_to_shopping(result_state)

from app.agent.mapper import state_to_response
from app.services import agent_service
from app.services import webview_progress_service


def test_webview_status_default_matches_frontend_contract():
    """웹뷰 시작 전에도 프론트가 기대하는 progress 필드를 항상 내려준다."""
    conversation_id = 999001
    webview_progress_service.clear_progress(conversation_id)

    status = webview_progress_service.get_status_or_default(conversation_id)

    assert status["type"] == "webview_progress"
    assert status["conversationId"] == conversation_id
    assert status["status"] == "waiting"
    assert status["step"] == "not_started"
    assert status["message"]
    assert status["screenshotUrl"] == (
        f"/api/agent/conversations/{conversation_id}/webview/screenshot"
    )


def test_webview_status_normalizes_legacy_idle_payload():
    """예전 서버 메모리의 idle payload도 현재 프론트 계약 형태로 보정한다."""
    conversation_id = 999006
    webview_progress_service.clear_progress(conversation_id)
    webview_progress_service._latest_status[conversation_id] = {
        "type": "webview_progress",
        "conversationId": conversation_id,
        "status": "idle",
    }

    status = webview_progress_service.get_status_or_default(conversation_id)

    assert status["status"] == "waiting"
    assert status["step"] == "not_started"
    assert status["message"]
    assert status["screenshotUrl"] == (
        f"/api/agent/conversations/{conversation_id}/webview/screenshot"
    )


def test_webview_progress_emit_always_includes_screenshot_url():
    """캡처가 아직 없어도 프론트가 같은 screenshotUrl을 폴링할 수 있어야 한다."""
    conversation_id = 999004
    webview_progress_service.clear_progress(conversation_id)

    status = webview_progress_service.emit_progress(
        conversation_id,
        step="payment_ready",
        message="주문 준비가 완료되었습니다.",
        flow="payment",
        status="waiting_user_action",
    )

    assert status["step"] == "payment_ready"
    assert status["message"] == "주문 준비가 완료되었습니다."
    assert status["screenshotUrl"] == (
        f"/api/agent/conversations/{conversation_id}/webview/screenshot"
    )
    assert webview_progress_service.get_latest_status(conversation_id) == status


def test_messages_address_confirm_can_trigger_order_creation():
    """주소 확인 수락도 /messages 자연어 흐름에서 주문 생성 후처리 대상이다."""
    assert agent_service._should_create_order_from_message(
        {"intent": "confirm"},
        "address_confirm",
    )


def test_real_browser_unsupported_platform_records_failed_progress(monkeypatch):
    """실제 브라우저 모드에서 지원하지 않는 플랫폼은 idle 대신 failed progress를 남긴다."""
    conversation_id = 999005
    webview_progress_service.clear_progress(conversation_id)
    monkeypatch.setenv("USE_REAL_BROWSER", "true")

    status = agent_service._emit_real_browser_progress(
        conversation_id,
        selected_product={"platform": "naver"},
        order_bundle={"order": {"id": 77}},
        payment_bundle={"payment": {"id": 88}},
        assistant_message="주문 준비가 완료되었습니다.",
    )

    assert status["status"] == "failed"
    assert status["step"] == "payment_automation_unsupported"
    assert status["screenshotUrl"] == (
        f"/api/agent/conversations/{conversation_id}/webview/screenshot"
    )
    assert status["meta"]["orderId"] == 77
    assert status["meta"]["paymentId"] == 88
    assert status["meta"]["error"] == "unsupported_real_browser_platform"


def test_product_pending_confirmation_uses_documented_actions():
    """내부 accept 액션은 API 명세의 order_now로 정규화한다."""
    response = state_to_response(
        {
            "stage": "product_confirming",
            "messages": [{"role": "assistant", "content": "이걸로 주문할까요?"}],
            "pending_action": {
                "type": "product_confirm",
                "message": "이걸로 주문할까요?",
                "payload": {
                    "recommendationItemId": 10,
                    "actions": ["accept", "reject"],
                },
            },
        },
        conversation_id=999002,
    )

    assert response.pendingConfirmation == {
        "type": "product",
        "message": "이걸로 주문할까요?",
        "payload": {
            "actions": ["order_now", "add_to_cart", "reject"],
            "recommendationItemId": 10,
        },
    }


def test_price_change_pending_confirmation_uses_documented_type():
    """가격 변경 확인은 clarification이 아니라 price_changed로 내려준다."""
    response = state_to_response(
        {
            "stage": "payment",
            "messages": [{"role": "assistant", "content": "가격이 바뀌었어요."}],
            "pending_action": {
                "type": "price_change_confirm",
                "message": "가격이 바뀌었어요. 계속 진행할까요?",
                "payload": {
                    "history_price": 9900,
                    "current_price": 12000,
                },
            },
        },
        conversation_id=999003,
    )

    assert response.status == "payment_in_progress"
    assert response.stage == "payment_precheck"
    assert response.pendingConfirmation == {
        "type": "price_changed",
        "message": "가격이 바뀌었어요. 계속 진행할까요?",
        "payload": {
            "history_price": 9900,
            "current_price": 12000,
            "subType": "price_change_confirm",
        },
    }

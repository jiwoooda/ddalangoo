from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.repositories import user_preference_repository
from app.schemas.payment import WebviewResultRequest
from app.services import payment_service


class _FakeResult:
    def __init__(self, payload=None):
        self._payload = payload

    def model_dump(self, by_alias: bool = False):
        return self._payload or {}


async def _fake_get_conversation(_db, conversation_id):
    return {"id": conversation_id, "user_id": 6}


async def _fake_get_order(_db, order_id):
    return {
        "id": order_id,
        "conversation_id": 125,
        "user_id": 6,
        "cart_id": 75,
        "status": "payment_pending",
    }


async def _fake_get_payment(_db, payment_id):
    return {"id": payment_id, "order_id": 77, "payment_status": "pending_user_action"}


async def _fake_update_payment(_db, payment_id, *, payment_status, failure_reason=None):
    return {"id": payment_id, "order_id": 77, "payment_status": payment_status}


async def _fake_update_order(_db, order_id, *, status, failed_reason=None):
    return {"id": order_id, "status": status}


async def _fake_update_conversation(_db, conversation_id, data):
    return {"id": conversation_id, **data}


async def _fake_create_event(_db, **kwargs):
    return kwargs


@pytest.mark.anyio
async def test_webview_success_creates_purchase_histories(monkeypatch):
    """completed/success/paid는 구매이력을 만들고 LangGraph를 재실행하지 않는다."""
    calls = {"history": 0, "resume": 0, "update_state": 0}

    async def _fake_create_histories(_db, conversation_id, user_id, payment_id=None):
        calls["history"] += 1
        return {"success": True, "count": 2, "history_ids": [1, 2]}

    async def _fake_resume(conversation_id, patch):
        calls["resume"] += 1
        raise AssertionError("completed 결과는 LangGraph를 재실행하면 안 된다")

    async def _fake_update_state(conversation_id, patch):
        calls["update_state"] += 1
        return {"stage": patch["stage"], "assistant_message": "결제가 완료되었습니다."}

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.payment_repository, "update_payment_status_db", _fake_update_payment)
    monkeypatch.setattr(payment_service.order_repository, "update_order_status_db", _fake_update_order)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.agent_event_repository, "create_agent_event_db", _fake_create_event)
    monkeypatch.setattr(payment_service.purchase_history_service, "create_histories_from_order_db", _fake_create_histories)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "inject_and_resume", _fake_resume)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(result="completed", orderId=77, paymentId=88),
    )

    assert calls["history"] == 1
    assert calls["resume"] == 0
    assert calls["update_state"] == 1
    assert result["stage"] == "completed"
    assert result["status"] == "order_completed"
    assert result["uiCommand"] == {"type": "close_webview"}


@pytest.mark.anyio
async def test_webview_cart_added_returns_cart_shopping_without_graph_resume(monkeypatch):
    """cart_added는 결제 precheck로 가지 않고 더 살지/결제할지 질문한다."""
    calls = {"resume": 0, "update_state": 0}

    async def _fake_resume(conversation_id, patch):
        calls["resume"] += 1
        raise AssertionError("cart_added 결과는 LangGraph를 재실행하면 안 된다")

    async def _fake_update_state(conversation_id, patch):
        calls["update_state"] += 1
        return patch

    async def _fake_get_cart(_db, cart_id):
        return {"id": cart_id, "status": "active", "conversation_id": 125}

    async def _fake_get_cart_items(_db, cart_id):
        return [
            {
                "id": 900,
                "recommendation_item_id": 518,
                "product_id": 168,
                "product_name_snapshot": "[달래해장] 속 풀리는 우삼겹 소곱창전골",
                "option_snapshot": None,
                "quantity": 1,
                "unit_price_snapshot": 12900,
            }
        ]

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.cart_repository, "get_cart_by_id_db", _fake_get_cart)
    monkeypatch.setattr(payment_service.cart_repository, "get_cart_items_by_cart_id_db", _fake_get_cart_items)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "inject_and_resume", _fake_resume)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(result="cart_added", orderId=77, paymentId=88),
    )

    assert calls["resume"] == 0
    assert calls["update_state"] == 1
    assert result["stage"] == "cart_shopping"
    assert result["uiCommand"] == {"type": "close_webview"}
    assert result["pendingConfirmation"]["type"] == "payment"
    assert result["pendingConfirmation"]["payload"]["subType"] == "continue_shopping"
    assert result["cart"]["cartId"] == 75
    assert result["cart"]["lastCartItem"]["productName"] == "[달래해장] 속 풀리는 우삼겹 소곱창전골"
    assert result["cart"]["lastCartItem"]["quantity"] == 1


@pytest.mark.anyio
async def test_webview_payment_ready_mock_is_attempt_not_paid(monkeypatch):
    """payment_ready_mock은 실제 결제 완료가 아니라 결제 버튼 클릭 시도 완료로 기록한다."""
    calls = {"history": 0, "payment_status": None, "order_status": None, "update_state": 0}

    async def _fake_create_histories(_db, conversation_id, user_id, payment_id=None):
        calls["history"] += 1
        return {"success": True, "count": 1, "history_ids": [1]}

    async def _fake_update_payment(_db, payment_id, *, payment_status, failure_reason=None):
        calls["payment_status"] = payment_status
        return {"id": payment_id, "order_id": 77, "payment_status": payment_status}

    async def _fake_update_order(_db, order_id, *, status, failed_reason=None):
        calls["order_status"] = status
        return {"id": order_id, "status": status}

    async def _fake_update_state(conversation_id, patch):
        calls["update_state"] += 1
        return patch

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.payment_repository, "update_payment_status_db", _fake_update_payment)
    monkeypatch.setattr(payment_service.order_repository, "update_order_status_db", _fake_update_order)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.agent_event_repository, "create_agent_event_db", _fake_create_event)
    monkeypatch.setattr(payment_service.purchase_history_service, "create_histories_from_order_db", _fake_create_histories)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(result="payment_ready_mock", orderId=77, paymentId=88),
    )

    assert calls["history"] == 0
    assert calls["payment_status"] == "payment_button_attempted"
    assert calls["order_status"] is None
    assert calls["update_state"] == 1
    assert result["stage"] == "completed"
    assert result["status"] == "payment_button_attempted"
    assert result["order"]["status"] == "payment_pending"
    assert result["payment"]["paymentStatus"] == "payment_button_attempted"
    assert result["uiCommand"] == {"type": "close_webview"}


@pytest.mark.anyio
async def test_webview_address_checked_returns_address_confirming(monkeypatch):
    """address_checked는 웹뷰를 닫고 음성 배송지 확인 단계로 돌아온다."""
    calls = {"created": 0, "set_default": 0}

    async def _fake_update_state(conversation_id, patch):
        return patch

    async def _fake_get_default_address(_db, user_id):
        return {
            "id": 1,
            "user_id": user_id,
            "address_line1": "서울시 강남구 테헤란로",
            "address_line2": "101호",
            "is_default": True,
        }

    async def _fake_get_addresses(_db, user_id):
        return [await _fake_get_default_address(_db, user_id)]

    async def _fake_create_address(_db, data):
        calls["created"] += 1
        return {"id": 2, **data}

    async def _fake_set_default(_db, user_id, address_id):
        calls["set_default"] += 1
        return await _fake_get_default_address(_db, user_id)

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.address_repository, "get_default_address_by_user_id_db", _fake_get_default_address)
    monkeypatch.setattr(payment_service.address_repository, "get_addresses_by_user_id_db", _fake_get_addresses)
    monkeypatch.setattr(payment_service.address_repository, "create_address_db", _fake_create_address)
    monkeypatch.setattr(payment_service.address_repository, "set_default_address_db", _fake_set_default)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(
            result="address_checked",
            orderId=77,
            paymentId=88,
            addressLine1="서울시 강남구 테헤란로",
            addressLine2="101호",
        ),
    )

    assert result["stage"] == "address_confirming"
    assert result["uiCommand"] == {"type": "close_webview"}
    assert result["pendingConfirmation"]["type"] == "address"
    assert result["pendingConfirmation"]["payload"]["address"]["address_line1"] == "서울시 강남구 테헤란로"
    assert result["pendingConfirmation"]["payload"]["address"]["address_line2"] == "101호"
    assert "배송지" in result["assistantMessage"]
    assert "맞으세요" in result["assistantMessage"]
    assert calls == {"created": 0, "set_default": 0}


@pytest.mark.anyio
async def test_webview_address_checked_without_address_requests_retry(monkeypatch):
    """웹뷰와 DB 양쪽에서 주소를 못 찾으면 주소 확인 완료로 넘기지 않는다."""
    async def _fake_update_state(conversation_id, patch):
        return patch

    async def _fake_get_default_address(_db, user_id):
        return None

    async def _fake_get_addresses(_db, user_id):
        return []

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.address_repository, "get_default_address_by_user_id_db", _fake_get_default_address)
    monkeypatch.setattr(payment_service.address_repository, "get_addresses_by_user_id_db", _fake_get_addresses)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(result="address_checked", orderId=77, paymentId=88),
    )

    assert result["stage"] == "address_required"
    assert result["pendingConfirmation"]["type"] == "address_check_failed"
    assert result["deliveryAddress"] is None
    assert result["error"]["code"] == "ADDRESS_NOT_FOUND_IN_WEBVIEW"


@pytest.mark.anyio
async def test_webview_address_checked_creates_default_address_when_missing(monkeypatch):
    """웹뷰 배송지가 DB에 없으면 새 기본 배송지로 저장한 뒤 음성 확인한다."""
    calls = {"created_payload": None}

    async def _fake_update_state(conversation_id, patch):
        return patch

    async def _fake_get_default_address(_db, user_id):
        return None

    async def _fake_get_addresses(_db, user_id):
        return []

    async def _fake_create_address(_db, data):
        calls["created_payload"] = data
        return {"id": 10, **data}

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.address_repository, "get_default_address_by_user_id_db", _fake_get_default_address)
    monkeypatch.setattr(payment_service.address_repository, "get_addresses_by_user_id_db", _fake_get_addresses)
    monkeypatch.setattr(payment_service.address_repository, "create_address_db", _fake_create_address)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(
            result="address_checked",
            orderId=77,
            paymentId=88,
            addressLine1="서울시 용산구 서빙고로 17",
            addressLine2="301호",
            recipientName="방달봉",
            recipientPhone="010-0000-0000",
        ),
    )

    assert calls["created_payload"]["is_default"] is True
    assert calls["created_payload"]["address_line1"] == "서울시 용산구 서빙고로 17"
    assert calls["created_payload"]["address_line2"] == "301호"
    assert result["pendingConfirmation"]["payload"]["address"]["address_line1"] == "서울시 용산구 서빙고로 17"
    assert result["pendingConfirmation"]["payload"]["address"]["address_line2"] == "301호"
    assert "배송지" in result["assistantMessage"]
    assert "맞으세요" in result["assistantMessage"]


@pytest.mark.anyio
async def test_webview_address_checked_promotes_matching_saved_address(monkeypatch):
    """웹뷰 배송지가 기존 비기본 배송지와 같으면 새로 만들지 않고 기본 배송지로 올린다."""
    calls = {"created": 0, "set_default_id": None}

    async def _fake_update_state(conversation_id, patch):
        return patch

    async def _fake_get_default_address(_db, user_id):
        return {
            "id": 1,
            "user_id": user_id,
            "recipient_name": "방달봉",
            "recipient_phone": "010-0000-0000",
            "address_line1": "서울시 강남구 테헤란로",
            "address_line2": "101호",
            "is_default": True,
        }

    async def _fake_get_addresses(_db, user_id):
        return [
            await _fake_get_default_address(_db, user_id),
            {
                "id": 2,
                "user_id": user_id,
                "recipient_name": "방달봉",
                "recipient_phone": "010-0000-0000",
                "address_line1": "서울시 용산구 서빙고로 17",
                "address_line2": "301호",
                "is_default": False,
            },
        ]

    async def _fake_set_default(_db, user_id, address_id):
        calls["set_default_id"] = address_id
        return {
            "id": address_id,
            "user_id": user_id,
            "recipient_name": "방달봉",
            "recipient_phone": "010-0000-0000",
            "address_line1": "서울시 용산구 서빙고로 17",
            "address_line2": "301호",
            "is_default": True,
        }

    async def _fake_create_address(_db, data):
        calls["created"] += 1
        return {"id": 3, **data}

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.address_repository, "get_default_address_by_user_id_db", _fake_get_default_address)
    monkeypatch.setattr(payment_service.address_repository, "get_addresses_by_user_id_db", _fake_get_addresses)
    monkeypatch.setattr(payment_service.address_repository, "set_default_address_db", _fake_set_default)
    monkeypatch.setattr(payment_service.address_repository, "create_address_db", _fake_create_address)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(
            result="address_checked",
            orderId=77,
            paymentId=88,
            addressLine1="서울시 용산구 서빙고로 17",
            addressLine2="301호",
        ),
    )

    assert calls["created"] == 0
    assert calls["set_default_id"] == 2
    assert result["deliveryAddress"]["is_default"] is True
    assert result["deliveryAddress"]["address_line1"] == "서울시 용산구 서빙고로 17"
    assert result["deliveryAddress"]["address_line2"] == "301호"
    assert "배송지" in result["assistantMessage"]
    assert "맞으세요" in result["assistantMessage"]


@pytest.mark.anyio
async def test_webview_cancelled_or_failed_does_not_create_purchase_histories(monkeypatch):
    """cancelled/failed는 구매이력을 만들지 않는다."""
    calls = {"history": 0}

    async def _fake_create_histories(_db, conversation_id, user_id, payment_id=None):
        calls["history"] += 1
        return {"success": True, "count": 1, "history_ids": [1]}

    async def _fake_update_state(conversation_id, patch):
        return patch

    monkeypatch.setattr(payment_service.conversation_repository, "get_conversation_by_id_db", _fake_get_conversation)
    monkeypatch.setattr(payment_service.order_repository, "get_order_by_id_db", _fake_get_order)
    monkeypatch.setattr(payment_service.payment_repository, "get_payment_by_id_db", _fake_get_payment)
    monkeypatch.setattr(payment_service.payment_repository, "update_payment_status_db", _fake_update_payment)
    monkeypatch.setattr(payment_service.order_repository, "update_order_status_db", _fake_update_order)
    monkeypatch.setattr(payment_service.conversation_repository, "update_conversation_db", _fake_update_conversation)
    monkeypatch.setattr(payment_service.agent_event_repository, "create_agent_event_db", _fake_create_event)
    monkeypatch.setattr(payment_service.purchase_history_service, "create_histories_from_order_db", _fake_create_histories)
    monkeypatch.setattr(payment_service.webview_progress_service, "clear_progress", lambda _conversation_id: None)
    monkeypatch.setattr(payment_service.runtime, "update_state", _fake_update_state)

    await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(result="cancelled", orderId=77, paymentId=88),
    )
    await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(result="failed", orderId=77, paymentId=88),
    )

    assert calls["history"] == 0


def test_user_preference_cache_uses_db_and_ttl(monkeypatch):
    """user_preference_cache는 JSON fallback 없이 DB row와 computed_at TTL을 사용한다."""
    now = datetime.now(UTC)
    saved = {}

    monkeypatch.setattr(user_preference_repository, "_database_url", lambda: "postgresql+psycopg://example")
    monkeypatch.setattr(
        user_preference_repository,
        "_get_cache_row",
        lambda user_id, preference_type, keywords_key="": SimpleNamespace(
            preference_data={"brand": "KF365"},
            computed_at=now - timedelta(hours=1),
        ),
    )
    monkeypatch.setattr(
        user_preference_repository,
        "_save_cache_row",
        lambda user_id, **kwargs: saved.update({"user_id": user_id, **kwargs}),
    )

    assert user_preference_repository.get_general_preference(6)["brand"] == "KF365"
    user_preference_repository.save_general_preference(6, {"brand": "KF365"})
    assert saved["preference_type"] == "general"
    assert saved["preference_data"] == {"brand": "KF365"}


def test_user_preference_cache_expired_returns_none(monkeypatch):
    """computed_at이 24시간을 넘으면 캐시 miss로 본다."""
    monkeypatch.setattr(user_preference_repository, "_database_url", lambda: "postgresql+psycopg://example")
    monkeypatch.setattr(
        user_preference_repository,
        "_get_cache_row",
        lambda user_id, preference_type, keywords_key="": SimpleNamespace(
            preference_data={"brand": "KF365"},
            computed_at=datetime.now(UTC) - timedelta(hours=25),
        ),
    )

    assert user_preference_repository.get_general_preference(6) is None

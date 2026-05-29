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
    return {"id": order_id, "conversation_id": 125, "user_id": 6, "status": "payment_pending"}


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
    """completed/success/paid에서만 payment_service가 구매이력 저장을 호출한다."""
    calls = {"history": 0}

    async def _fake_create_histories(_db, conversation_id, user_id, payment_id=None):
        calls["history"] += 1
        return {"success": True, "count": 2, "history_ids": [1, 2]}

    async def _fake_resume(conversation_id, patch):
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
    monkeypatch.setattr("app.agent.mapper.state_to_response", lambda state, conversation_id: _FakeResult(state))

    result = await payment_service.handle_webview_result_db(
        None,
        125,
        WebviewResultRequest(result="completed", orderId=77, paymentId=88),
    )

    assert calls["history"] == 1
    assert result["stage"] == "completed"


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

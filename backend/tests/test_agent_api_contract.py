import asyncio
from app.agent.mapper import state_to_response
from app.repositories import product_repository, user_preference_repository
from app.routers import agent as agent_router
from app.agent import recommendation_sync
from app.services import agent_service
from app.services import webview_progress_service
from app.utils.product_url_contract import (
    canonical_product_url_for_platform,
    fallback_product_fingerprint,
    is_kurly_goods_url,
)
from src.agents import platform_agent
from src.tools import meta_mcp_client


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


def test_webview_progress_recovers_status_and_screenshot_from_disk(monkeypatch, tmp_path):
    """프로세스 메모리가 비어도 디스크에 저장된 마지막 progress를 복원한다."""
    conversation_id = 999009
    monkeypatch.setattr(webview_progress_service, "_SCREENSHOT_DIR", tmp_path)
    webview_progress_service.clear_progress(conversation_id)

    status = webview_progress_service.emit_progress(
        conversation_id,
        step="opening_shop",
        message="컬리에 접속하고 있어요.",
        flow="new_purchase",
        status="running",
        screenshot_bytes=b"fake-jpeg-bytes",
    )

    webview_progress_service._latest_status.pop(conversation_id, None)
    webview_progress_service._latest_screenshot.pop(conversation_id, None)

    assert webview_progress_service.get_status_or_default(conversation_id) == status
    assert webview_progress_service.get_latest_screenshot(conversation_id) == b"fake-jpeg-bytes"


def test_user_preference_repository_noops_when_database_url_missing(monkeypatch):
    """MVP에서는 JSON fallback 없이 DB URL이 없으면 캐시 miss/no-op으로 동작한다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    user_preference_repository.save_general_preference(1, {"summary": "healthy"})
    user_preference_repository.save_keyword_preference(1, ["치즈", "모짜렐라"], [{"product_name": "치즈"}])

    assert user_preference_repository.get_general_preference(1) is None
    assert user_preference_repository.get_keyword_preference(1, ["모짜렐라", "치즈"]) is None


def test_cancel_conversation_endpoint_requests_webview_cancel(monkeypatch):
    """cancel endpoint는 Playwright cancel event를 세팅하는 함수만 호출하면 된다."""
    called = {}

    def fake_request_cancel():
        called["request_cancel"] = True

    monkeypatch.setattr("src.tools.webview_tool.request_cancel", fake_request_cancel)

    response = asyncio.run(agent_router.cancel_conversation(123))

    assert response == {"ok": True}
    assert called["request_cancel"] is True


def test_messages_address_confirm_can_trigger_order_creation():
    """주소 확인 수락도 /messages 자연어 흐름에서 주문 생성 후처리 대상이다."""
    assert agent_service._should_create_order_from_message(
        {"intent": "confirm"},
        "address_confirm",
        "응",
    )


def test_payment_method_confirm_rejects_ambiguous_confirmation_text():
    """결제수단 확인에서 '음'은 명시적 동의가 아니므로 주문 생성 후처리를 막는다."""
    assert agent_service._should_create_order_from_message(
        {"intent": "confirm"},
        "payment_method_confirm",
        "음",
    ) is False


def test_payment_method_confirm_accepts_explicit_payment_text():
    """결제수단 확인은 결제 의사가 명확한 발화에서만 주문 생성으로 이어진다."""
    assert agent_service._should_create_order_from_message(
        {"intent": "confirm"},
        "payment_method_confirm",
        "결제할래",
    ) is True


def test_payment_confirmation_accepts_compact_affirmative_text():
    """공백 없이 붙은 '응그래'도 명시적 확인으로 처리한다."""
    assert agent_service._is_explicit_payment_confirmation("응 그래") is True
    assert agent_service._is_explicit_payment_confirmation("응그래") is True


def test_webview_task_payload_uses_cart_url_for_address_and_payment_tasks():
    """배송지/결제 WebView는 상품 검색 URL이 아니라 장바구니 URL에서 시작한다."""
    state = {
        "selected_product": {
            "platform": "kurly",
            "product_name": "곱창전골",
            "product_url": "https://www.kurly.com/search?sword=곱창전골",
        },
        "order": {"orderId": 74, "status": "payment_pending"},
        "payment": {"paymentId": 74, "paymentStatus": "pending_user_action"},
    }

    address_payload = agent_service._webview_task_payload(
        task="address_check",
        state=state,
    )
    payment_payload = agent_service._webview_task_payload(
        task="payment",
        state=state,
    )

    assert address_payload["startUrl"] == "https://www.kurly.com/cart"
    assert address_payload["url"] == "https://www.kurly.com/cart"
    assert payment_payload["startUrl"] == "https://www.kurly.com/cart"
    assert payment_payload["url"] == "https://www.kurly.com/cart"


def test_webview_task_payload_uses_product_url_for_add_to_cart():
    """장바구니 담기 WebView만 상품 URL에서 시작한다."""
    state = {
        "selected_product": {
            "platform": "kurly",
            "product_name": "곱창전골",
            "product_url": "https://www.kurly.com/search?sword=곱창전골",
        },
        "quantity": 2,
        "order": {"orderId": 74, "status": "payment_pending"},
        "payment": {"paymentId": 74, "paymentStatus": "pending_user_action"},
    }

    payload = agent_service._webview_task_payload(task="add_to_cart", state=state)

    assert payload["startUrl"] == "https://www.kurly.com/search?sword=곱창전골"
    assert payload["url"] == "https://www.kurly.com/search?sword=곱창전골"
    assert payload["targetProductName"] == "곱창전골"
    assert payload["quantity"] == 2


def test_state_has_delivery_address_requires_non_empty_address():
    """배송지 확인 수락은 실제 주소가 state에 있을 때만 결제로 이어질 수 있다."""
    assert agent_service._state_has_delivery_address({"delivery_address": None}) is False
    assert agent_service._state_has_delivery_address(
        {"delivery_address": {"address_line1": "서울시 용산구", "address_line2": "301호"}}
    ) is True


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


def test_real_browser_kurly_product_records_searching_progress(monkeypatch):
    """컬리 상품은 실제 브라우저 모드에서 검색 진행 상태로 시작한다."""
    conversation_id = 999007
    webview_progress_service.clear_progress(conversation_id)
    monkeypatch.setenv("USE_REAL_BROWSER", "true")

    status = agent_service._emit_real_browser_progress(
        conversation_id,
        selected_product={
            "platform": "kurly",
            "product_url": "https://www.kurly.com/search?sword=아보카도",
        },
        order_bundle={"order": {"id": 79}},
        payment_bundle={"payment": {"id": 90}},
        assistant_message="주문 준비가 완료되었습니다.",
    )

    assert status["status"] == "running"
    assert status["step"] == "searching_product"
    assert status["message"] == "컬리에서 상품을 찾고 있어요."
    assert status["meta"]["platform"] == "kurly"


def test_real_browser_kurly_order_starts_background_worker(monkeypatch):
    """주문 확정 후에는 실제 Playwright 작업을 별도 스레드로 시작한다."""
    started_thread = {}

    class FakeThread:
        """테스트에서는 브라우저를 띄우지 않고 스레드 시작 여부만 기록한다."""

        def __init__(self, *, target, daemon, name):
            started_thread["target"] = target
            started_thread["daemon"] = daemon
            started_thread["name"] = name

        def start(self):
            started_thread["started"] = True

    monkeypatch.setenv("USE_REAL_BROWSER", "true")
    monkeypatch.setattr(agent_service.threading, "Thread", FakeThread)

    agent_service._start_real_browser_purchase(
        999008,
        selected_product={
            "platform": "kurly",
            "product_name": "아보카도",
            "product_url": "https://www.kurly.com/search?sword=아보카도",
        },
        order_bundle={
            "order": {"id": 101},
            "order_items": [{"quantity": 2}],
        },
        payment_bundle={"payment": {"id": 202}},
    )

    assert started_thread["started"] is True
    assert started_thread["daemon"] is True
    assert started_thread["name"] == "kurly-webview-999008"
    assert callable(started_thread["target"])


def test_product_url_contract_does_not_treat_kurly_search_as_canonical():
    """컬리 검색 URL은 WebView 진입용일 뿐 상품 dedup canonical URL이 아니다."""
    search_url = "https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94"
    goods_url = "https://www.kurly.com/goods/123456"

    assert canonical_product_url_for_platform("kurly", search_url) is None
    assert canonical_product_url_for_platform("kurly", goods_url) == goods_url
    assert is_kurly_goods_url(goods_url) is True


def test_fallback_fingerprint_keeps_distinct_kurly_search_candidates_apart():
    """같은 검색 URL에서 온 서로 다른 후보는 상품명/가격/이미지 fingerprint로 분리된다."""
    first = fallback_product_fingerprint(
        platform="kurly",
        product_name="유기농 조각 양배추 300g",
        price=2750,
        image_url="https://image.example/cabbage-300.jpg",
    )
    second = fallback_product_fingerprint(
        platform="kurly",
        product_name="한통 양배추 900g",
        price=3490,
        image_url="https://image.example/cabbage-900.jpg",
    )

    assert first
    assert second
    assert first != second


def test_product_repository_identity_uses_fingerprint_for_kurly_search_url():
    """repository 식별키도 검색 URL hash가 아니라 후보 fingerprint를 사용한다."""
    search_url = "https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94"
    identity = product_repository._candidate_identity_contract(
        {
            "platform": "kurly",
            "product_url": search_url,
            "price": 2750,
            "image_url": "https://image.example/cabbage.jpg",
        },
        "유기농 조각 양배추 300g",
    )

    assert identity["execution_url"] == search_url
    assert identity["canonical_product_url"] is None
    assert identity["identity_strategy"] == "fallback_fingerprint"
    assert identity["identity_hash"] != product_repository.external_product_url_hash(search_url)


def test_product_repository_marks_legacy_kurly_search_mapping_as_ignored():
    """기존 DB에 남은 컬리 검색 URL mapping은 product_id 재사용 근거로 쓰지 않는다."""
    mapping = product_repository.ExternalProductMapping(
        platform="kurly",
        external_product_url="https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94",
        external_product_url_hash="legacy-search-hash",
    )

    assert product_repository._is_legacy_search_url_mapping(mapping) is True


def test_recommendation_sync_ignores_shared_kurly_search_url_when_matching():
    """동일한 검색 URL만 같고 상품명이 다르면 같은 추천 후보로 보지 않는다."""
    search_url = "https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94"

    assert recommendation_sync._same_product(
        {
            "platform": "kurly",
            "product_name": "유기농 조각 양배추 300g",
            "product_url": search_url,
        },
        {
            "platform": "kurly",
            "product_name": "한통 양배추 900g",
            "product_url": search_url,
        },
    ) is False


def test_recommendation_sync_does_not_treat_product_id_as_recommendation_item_id():
    """candidate.id는 product id일 수 있으므로 recommendation_item_id로 쓰면 안 된다."""
    assert recommendation_sync._recommendation_item_id({"id": 473}) is None
    assert recommendation_sync._recommendation_item_id({"recommendationItemId": 473}) == 473


def test_webview_order_input_uses_recommendation_item_snapshot():
    """WebView 실행 입력은 product_id가 아니라 recommendation_item_id snapshot에서 만든다."""
    webview_input = agent_service._webview_input_from_recommendation_item(
        user_id=1,
        conversation_id=999009,
        recommendation_item_id=321,
        recommendation_item={
            "recommendation_item_id": 321,
            "platform": "kurly",
            "product_name": "유기농 조각 양배추 300g",
            "product_url": "https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94",
            "price": 2750,
        },
        selected_product={
            "platform": "kurly",
            "product_name": "다른 state 상품명",
            "product_url": "https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94",
        },
        order_bundle={
            "order_items": [
                {"recommendation_item_id": 321, "quantity": 3},
            ],
        },
    )

    assert webview_input.recommendation_item_id == 321
    assert webview_input.execution_url == "https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94"
    assert webview_input.canonical_product_url is None
    assert webview_input.target_product_name == "유기농 조각 양배추 300g"
    assert webview_input.expected_price == 2750
    assert webview_input.quantity == 3


def test_webview_chromium_launch_options_include_railway_args():
    """Railway Chromium 실행에는 sandbox/dev-shm 회피 옵션이 포함되어야 한다."""
    from src.tools import webview_tool

    original_browser = webview_tool.WEBVIEW_BROWSER
    try:
        webview_tool.WEBVIEW_BROWSER = "chromium"
        launch_options = webview_tool._browser_launch_options()
    finally:
        webview_tool.WEBVIEW_BROWSER = original_browser

    assert launch_options["headless"] is True
    assert "--no-sandbox" in launch_options["args"]
    assert "--disable-setuid-sandbox" in launch_options["args"]
    assert "--disable-dev-shm-usage" in launch_options["args"]
    assert "--disable-gpu" in launch_options["args"]
    assert "--single-process" in launch_options["args"]
    assert "--no-zygote" in launch_options["args"]


def test_webview_screenshot_disabled_skips_page_call(monkeypatch):
    """WEBVIEW_SCREENSHOT_ENABLED=false면 page.screenshot 자체를 호출하지 않는다."""
    from src.tools import webview_tool

    class CrashIfCalledPage:
        def screenshot(self, **kwargs):
            raise AssertionError("screenshot should not be called")

    monkeypatch.setattr(webview_tool, "WEBVIEW_SCREENSHOT_ENABLED", False)

    assert webview_tool._safe_screenshot(CrashIfCalledPage()) is None


def test_webview_credential_debug_summary_hides_secret_values(monkeypatch):
    """로그인 진단 로그는 credential 원문 대신 존재 여부와 길이만 남긴다."""
    from src.tools import webview_tool

    monkeypatch.setattr(webview_tool, "KURLY_EMAIL", "user@example.com")
    monkeypatch.setattr(webview_tool, "KURLY_PASSWORD", "secret-password")

    summary = webview_tool._credential_debug_summary()

    assert summary == {
        "email_present": True,
        "email_length": len("user@example.com"),
        "password_present": True,
        "password_length": len("secret-password"),
    }
    assert "user@example.com" not in str(summary)
    assert "secret-password" not in str(summary)


def test_kurly_mvp_mode_selects_kurly_first(monkeypatch):
    """실제 브라우저 MVP에서는 아보카도 같은 신선식품을 컬리 후보로 검색한다."""
    monkeypatch.setenv("USE_REAL_BROWSER", "true")

    platforms = platform_agent._select_platforms(
        {"keywords": ["아보카도"]},
        {},
    )

    assert platforms == ["kurly"]


def test_meta_mcp_sse_parser_reads_search_result_event():
    """분리된 meta-mcp /sse 응답에서 search_result 이벤트를 상품 목록으로 변환한다."""
    payload = "\n".join([
        "event: progress",
        'data: {"status":"running"}',
        "",
        "event: search_result",
        'data: {"total":1,"products":[{"platform":"kurly","name":"모짜렐라","price":6780,"delivery_info":"","url":"https://www.kurly.com/search?sword=cheese","image_url":"https://example.com/image.jpg"}]}',
        "",
    ])

    products = meta_mcp_client._parse_sse_search_result(payload)

    assert products == [
        {
            "product_name": "모짜렐라",
            "price": 6780,
            "rating": None,
            "review_count": None,
            "delivery": "",
            "delivery_fee": None,
            "platform": "kurly",
            "image_url": "https://example.com/image.jpg",
            "product_url": "https://www.kurly.com/search?sword=cheese",
            "execution_url": "https://www.kurly.com/search?sword=cheese",
            "source_url": None,
            "is_sold_out": False,
            "raw": {
                "platform": "kurly",
                "name": "모짜렐라",
                "price": 6780,
                "delivery_info": "",
                "url": "https://www.kurly.com/search?sword=cheese",
                "image_url": "https://example.com/image.jpg",
            },
        }
    ]


def test_meta_mcp_sse_parser_rewrites_kurly_smartstore_url():
    """remote meta-mcp가 smartstore URL을 줘도 컬리 WebView 실행 URL로 분리한다."""
    smartstore_url = "https://smartstore.naver.com/main/products/12924602621"
    payload = "\n".join([
        "event: search_result",
        (
            'data: {"total":1,"products":[{"platform":"kurly","name":"유기농 조각 양배추 300g",'
            f'"price":2750,"delivery_info":"","url":"{smartstore_url}",'
            '"image_url":"https://example.com/cabbage.jpg"}]}'
        ),
        "",
    ])

    products = meta_mcp_client._parse_sse_search_result(payload, query="양배추")

    assert len(products) == 1
    product = products[0]
    expected_execution_url = "https://www.kurly.com/search?sword=%EC%96%91%EB%B0%B0%EC%B6%94"

    assert product["platform"] == "kurly"
    assert product["product_name"] == "유기농 조각 양배추 300g"
    assert product["price"] == 2750
    assert product["image_url"] == "https://example.com/cabbage.jpg"
    assert product["source_url"] == smartstore_url
    assert product["product_url"] == expected_execution_url
    assert product["execution_url"] == expected_execution_url
    assert product["raw"]["source_url"] == smartstore_url
    assert product["raw"]["url"] == expected_execution_url
    assert product["raw"]["execution_url"] == expected_execution_url


def test_kurly_mvp_fallback_does_not_require_naver_credentials(monkeypatch):
    """실제 브라우저 MVP에서는 Naver 키가 없어도 컬리 검색 URL 후보를 만든다."""
    monkeypatch.setenv("USE_REAL_BROWSER", "true")
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)

    products = meta_mcp_client._call_naver_search_api({
        "query": "아보카도",
        "platforms": ["kurly"],
        "sort": "price_low",
        "limit": 5,
    })

    assert products == [
        {
            "product_name": "아보카도",
            "price": 0,
            "rating": None,
            "review_count": None,
            "delivery": "",
            "delivery_fee": None,
            "platform": "kurly",
            "image_url": None,
            "product_url": "https://www.kurly.com/search?sword=%EC%95%84%EB%B3%B4%EC%B9%B4%EB%8F%84",
            "execution_url": "https://www.kurly.com/search?sword=%EC%95%84%EB%B3%B4%EC%B9%B4%EB%8F%84",
            "source_url": None,
            "is_sold_out": False,
            "raw": {
                "name": "아보카도",
                "price": 0,
                "delivery_info": "",
                "platform": "kurly",
                "image_url": None,
                "url": "https://www.kurly.com/search?sword=%EC%95%84%EB%B3%B4%EC%B9%B4%EB%8F%84",
                "source": "kurly_search_url_fallback",
            },
        }
    ]


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


def test_blocked_product_confirmation_does_not_readd_order_actions():
    """주문 불가 후보는 pending actions에 order_now를 다시 붙이지 않는다."""
    response = state_to_response(
        {
            "stage": "product_confirming",
            "messages": [{"role": "assistant", "content": "컬리 상품만 지원해요."}],
            "pending_action": {
                "type": "product_confirm",
                "message": "컬리 상품만 지원해요.",
                "payload": {
                    "recommendationItemId": 10,
                    "actions": ["reject"],
                    "orderBlockReason": "real_browser_requires_kurly",
                },
            },
        },
        conversation_id=999008,
    )

    assert response.pendingConfirmation["payload"]["actions"] == ["reject"]
    assert response.pendingConfirmation["payload"]["orderBlockReason"] == "real_browser_requires_kurly"


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


def test_webview_cart_task_contract_after_quantity_confirmation():
    """수량 확정 뒤 응답은 결제 확인이 아니라 add_to_cart WebView task여야 한다."""
    response = state_to_response(
        {
            "stage": "webview_cart",
            "messages": [{"role": "assistant", "content": "네, 멜론 5개를 장바구니에 담을게요."}],
            "pending_action": {
                "type": "webview_task",
                "message": "네, 멜론 5개를 장바구니에 담을게요.",
                "payload": {
                    "task": "add_to_cart",
                    "orderId": 77,
                    "paymentId": 88,
                    "platform": "kurly",
                    "productName": "멜론",
                    "quantity": 5,
                    "startUrl": "https://www.kurly.com/goods/123",
                    "url": "https://www.kurly.com/goods/123",
                    "uiCommand": {"type": "open_webview", "task": "add_to_cart"},
                },
            },
        },
        conversation_id=999009,
    )

    assert response.status == "cart_processing"
    assert response.stage == "webview_cart"
    assert response.pendingConfirmation["type"] == "webview_task"
    assert response.pendingConfirmation["payload"]["task"] == "add_to_cart"
    assert response.pendingConfirmation["payload"]["startUrl"] == "https://www.kurly.com/goods/123"
    assert response.uiCommand == {"type": "open_webview", "task": "add_to_cart"}

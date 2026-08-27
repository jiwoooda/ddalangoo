"""WON-22 Unit 10 — queue_items와 ProductRequest 연결. 완료 조건 중
"한 품목 실패가 다른 품목 identity를 오염시키지 않게 처리"를 직접 검증한다."""
from src.agents.purchase_queue_agent import _normalize_queue_item, start_queue_item, advance_queue


def test_legacy_shape_gets_backfilled_with_category_request():
    # recipe_agent Mode 1이 아직도 만드는 구버전 shape(request 없음)
    legacy = {"name": "두부", "quantity": 1, "unit": "모"}
    normalized = _normalize_queue_item(legacy)
    assert normalized["resolution_status"] == "pending"
    assert normalized["request"]["category"] == "두부"
    assert normalized["request"]["match_mode"] == "category"
    assert normalized["request"]["brand"] is None


def test_existing_request_is_preserved_not_overwritten():
    item = {
        "name": "서울우유", "quantity": 1, "unit": "개",
        "request": {"category": "우유", "brand": "서울우유", "match_mode": "brand", "excluded_brands": []},
        "resolution_status": "pending",
    }
    normalized = _normalize_queue_item(item)
    assert normalized["request"]["brand"] == "서울우유"
    assert normalized["request"]["match_mode"] == "brand"


def test_one_item_request_does_not_leak_into_another():
    """핵심 완료 조건: 품목 A(브랜드 지정)의 request가 품목 B(카테고리만)에
    새어들면 안 된다 — 각 품목이 독립된 dict를 가져야 한다."""
    queue_items = [
        {
            "name": "서울우유", "quantity": 1, "unit": "개",
            "request": {"category": "우유", "brand": "서울우유", "match_mode": "brand", "excluded_brands": []},
            "resolution_status": "pending",
        },
        {"name": "계란", "quantity": 1, "unit": "개"},  # 구버전 shape, brand 없음
    ]
    state = {"queue_items": queue_items, "current_queue_index": 1}
    result = start_queue_item(state)
    assert result["product_request"]["brand"] is None
    assert result["product_request"]["category"] == "계란"
    # 원본 큐의 품목 0(서울우유)은 안 바뀌었는지도 확인
    assert queue_items[0]["request"]["brand"] == "서울우유"


def test_advance_queue_marks_completed_item_selected_without_touching_others():
    queue_items = [
        {
            "name": "서울우유", "quantity": 1, "unit": "개",
            "request": {"category": "우유", "brand": "서울우유", "match_mode": "brand", "excluded_brands": []},
            "resolution_status": "pending",
        },
        {
            "name": "계란", "quantity": 1, "unit": "개",
            "request": {"category": "계란", "brand": None, "match_mode": "category", "excluded_brands": []},
            "resolution_status": "pending",
        },
    ]
    state = {"queue_items": queue_items, "current_queue_index": 0, "queue_source": "multi_buy"}
    result = advance_queue(state)
    assert result["queue_items"][0]["resolution_status"] == "selected"
    assert result["queue_items"][1]["resolution_status"] == "pending"
    # 원본 리스트는 불변(방어적 복사) — 다른 곳에서 같은 리스트를 참조 중이어도 안전
    assert queue_items[0]["resolution_status"] == "pending"

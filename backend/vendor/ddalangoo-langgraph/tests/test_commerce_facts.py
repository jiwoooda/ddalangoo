"""Task 2 — commerce_facts 결정론적 추출기 케이스별 유닛 테스트.

Task 1 §2 문구 지점(P1–P22, R2/R3, N1–N7, C1–C4) 각각에 대해 실제 state 를
구성해 fact 번들을 만들고, Task 1 §4 매핑표와 일치하는지 확인한다.
WON-26 §5 의 5개 버그 상황을 일부러 재현해 fact 레벨 정규화/구분을 검증한다.

추출기는 아직 아무 노드에도 연결되지 않았다 — 순수 계산만 검증.
"""
import pytest

from src.utils import commerce_facts as cf


def b(awaiting, *facts):
    return {"state_facts": list(facts), "awaiting": awaiting}


# Task 1 §4 매핑표상 P1/P5/P13 은 의도적으로 전용 테스트가 없다 (커버리지 갭 아님):
# - P1: "완료 메시지 접미사" — 독립 fact 지점이 아니라 P21(order_placed)의
#   delivery_estimate 필드로 흡수된다 (test_P21_completion_with_delivery 참고).
# - P5: "P4 의 원래 pending 문구" — P4(unanswerable)가 새 문구를 만들 때 참고만 하는
#   이전 메시지일 뿐 그 자체가 fact 를 만들지 않는다 (§5-3: 접두어로도 안 붙인다).
# - P13: 단일 품목 수량변경/제거 경로 — P12 와 같은 트리거라 같은 fact 번들을
#   공유한다 (test_P12_quantity_change_emptied_cart 가 대표).


# ──────────────────────────────────────────────────────────────────────────
# payment/node.py 지점
# ──────────────────────────────────────────────────────────────────────────

def test_P2_delivery_question_answer_midflow():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "address_confirm"),
        cf.delivery_estimate("로켓배송", 0),
    )
    assert bundle == b(
        "address_confirm",
        {"fact_type": "delivery_estimate", "timing": "next_day", "raw_delivery_text": None, "fee_krw": 0},
    )


def test_P3_payment_method_question_answer():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "address_confirm"),
        cf.payment_method(),
    )
    assert bundle == b("address_confirm", {"fact_type": "payment_method", "method": "네이버페이"})


def test_P4_unanswerable_is_standalone_fact_no_prefix():
    # WON-26 §5-3: 원래 pending message 를 접두어로 붙이지 않는다
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_password"),
        cf.unanswerable(None),
    )
    assert bundle == b("payment_password", {"fact_type": "unanswerable", "topic_hint": None})


def test_P6_selection_validation_failed():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "idle", "clarification"),
        cf.selection_rechecking(),
    )
    assert bundle == b("selection_recheck", {"fact_type": "selection_rechecking"})


def test_P7_added_to_cart_multi():
    cart = [
        {"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 1, "total": 12900},
        {"keywords": ["우유"], "product_name": "서울우유 1L", "quantity": 2, "total": 5600},
    ]
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "cart_shopping", "continue_shopping"),
        cf.item_just_added(["우유"], "서울우유 1L", 2),
        cf.cart_contents(cart),
    )
    assert bundle == b(
        "continue_or_pay",
        {"fact_type": "item_just_added", "label": "우유", "quantity": 2},
        {"fact_type": "cart_contents", "item_count": 2, "total_krw": 18500,
         "items": [{"label": "딸기", "quantity": 1}, {"label": "우유", "quantity": 2}]},
    )


def test_P8_added_to_cart_single():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "cart_shopping", "continue_shopping"),
        cf.item_just_added(["참기름"], "오뚜기 참기름 500ml", 1),
        cf.single_item(["참기름"], "오뚜기 참기름 500ml", 1, 15900),
    )
    assert bundle == b(
        "continue_or_pay",
        {"fact_type": "item_just_added", "label": "참기름", "quantity": 1},
        {"fact_type": "single_item", "label": "참기름", "quantity": 1, "total_krw": 15900},
    )


def test_P9_no_product_to_pay():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "cart_shopping", "what_to_buy"),
        cf.no_product_to_pay(),
    )
    assert bundle == b("what_to_buy", {"fact_type": "no_product_to_pay"})


def test_P10_cart_review_with_cart():
    cart = [{"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 2, "total": 25800}]
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "cart_shopping", "cart_review"),
        cf.cart_contents(cart),
    )
    assert bundle == b(
        "cart_review",
        {"fact_type": "cart_contents", "item_count": 1, "total_krw": 25800,
         "items": [{"label": "딸기", "quantity": 2}]},
    )


def test_P11_cart_review_no_cart_single_item():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "cart_shopping", "cart_review"),
        cf.single_item(["딸기"], "설향 딸기 500g", 1, 12900),
    )
    assert bundle == b(
        "cart_review",
        {"fact_type": "single_item", "label": "딸기", "quantity": 1, "total_krw": 12900},
    )


def test_P12_quantity_change_emptied_cart():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "cart_shopping", "what_to_buy"),
        cf.cart_empty(),
    )
    assert bundle == b("what_to_buy", {"fact_type": "cart_empty"})


def test_P14_no_address_on_file():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "cart_shopping", "address_required"),
        cf.no_address_on_file(),
    )
    assert bundle == b("address_input", {"fact_type": "no_address_on_file"})


def test_P15_address_selected_confirm():
    addr = {"address_line1": "서울특별시 강남구 테헤란로 1길 10", "address_line2": "101호"}
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "address_confirm"),
        cf.address_selected(addr),
    )
    assert bundle == b(
        "address_confirm",
        {"fact_type": "address_selected", "address": "서울특별시 강남구 테헤란로..."},
    )


def test_P16_payment_method_choice_with_cart():
    cart = [{"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 1, "total": 12900}]
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_method_confirm"),
        cf.cart_contents(cart),
        cf.payment_method(),
    )
    assert bundle == b(
        "payment_method_choice",
        {"fact_type": "cart_contents", "item_count": 1, "total_krw": 12900,
         "items": [{"label": "딸기", "quantity": 1}]},
        {"fact_type": "payment_method", "method": "네이버페이"},
    )


def test_P17_payment_method_choice_no_cart():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_method_confirm"),
        cf.single_item(["딸기"], "설향 딸기 500g", 3, 12900),
        cf.payment_method(),
    )
    assert bundle == b(
        "payment_method_choice",
        {"fact_type": "single_item", "label": "딸기", "quantity": 3, "total_krw": 38700},
        {"fact_type": "payment_method", "method": "네이버페이"},
    )


def test_P18_payment_password():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_password"),
    )
    assert bundle == b("payment_password")


def test_P19_idempotency_conflict():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_retry_confirm"),
        cf.payment_error("idempotency_conflict"),
    )
    assert bundle == b(
        "payment_retry",
        {"fact_type": "payment_error", "kind": "idempotency_conflict", "retryable": True},
    )


def test_P20_generic_payment_failure():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_retry_confirm"),
        cf.payment_error("execution_error"),
    )
    assert bundle == b(
        "payment_retry",
        {"fact_type": "payment_error", "kind": "execution_error", "retryable": True},
    )


def test_P21_completion_with_delivery():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "completed", "payment_confirm"),
        cf.order_placed("ORDER-ABC123"),
        cf.delivery_estimate("샛별배송", 0),
    )
    assert bundle == b(
        "order_complete",
        {"fact_type": "order_placed", "order_id": "ORDER-ABC123"},
        {"fact_type": "delivery_estimate", "timing": "next_morning_7am", "raw_delivery_text": None, "fee_krw": 0},
    )


def test_P21_completion_without_delivery_info():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "completed", "payment_confirm"),
        cf.order_placed("ORDER-XYZ"),
    )
    assert bundle == b("order_complete", {"fact_type": "order_placed", "order_id": "ORDER-XYZ"})


def test_P22_fallback_branch():
    bundle = cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_method_confirm"),
        cf.single_item(["딸기"], "설향 딸기 500g", 1, 12900),
        cf.payment_method(),
    )
    assert bundle["awaiting"] == "payment_method_choice"


# ──────────────────────────────────────────────────────────────────────────
# response_agent.py 지점
# ──────────────────────────────────────────────────────────────────────────

def test_R2_address_on_file():
    addr = {"address_line1": "서울특별시 마포구 합정동 100", "address_line2": ""}
    bundle = cf.build_bundle(
        cf.derive_awaiting("response_agent", "idle", "address_confirm", intent="ask"),
        cf.address_on_file(addr),
    )
    assert bundle == b(
        "address_confirm",
        {"fact_type": "address_on_file", "address": "서울특별시 마포구 합정동 100"},
    )


def test_R3_no_address():
    bundle = cf.build_bundle(
        cf.derive_awaiting("response_agent", "idle", "address_confirm", intent="ask"),
        cf.no_address_on_file(),
    )
    # 승인 결정(후보 A): _answer_address_question 이 주소 유무와 무관하게
    # pending_action.type="address_confirm" 을 세팅하므로 R2/R3 의 awaiting 은
    # 동일하게 address_confirm. "주소 없음" 은 no_address_on_file state_fact 로
    # 전달되고, Voice 모듈이 그 조합으로 "배송지를 알려주세요" 문구를 만든다.
    # (Task 1 §4 표의 R3→address_input 은 이 결정으로 address_confirm 으로 정정)
    assert bundle == b("address_confirm", {"fact_type": "no_address_on_file"})


# ──────────────────────────────────────────────────────────────────────────
# nodes.py respond_node 폴백 지점
# ──────────────────────────────────────────────────────────────────────────

def test_N4_completed_fallback():
    bundle = cf.build_bundle(
        cf.derive_awaiting("respond", "completed", None),
        cf.order_placed("ORDER-N4"),
    )
    assert bundle == b("order_complete", {"fact_type": "order_placed", "order_id": "ORDER-N4"})


def test_N5_failed_fallback():
    bundle = cf.build_bundle(
        cf.derive_awaiting("respond", "failed", None),
        cf.payment_error("execution_error"),
    )
    assert bundle == b(
        "payment_retry",
        {"fact_type": "payment_error", "kind": "execution_error", "retryable": True},
    )


def test_N6_address_confirm_accepted_ack():
    assert cf.derive_awaiting("respond", "idle", "address_confirm", intent="confirm") == "none"


def test_N7_address_confirm_denied_wants_new_address():
    assert cf.derive_awaiting("respond", "idle", "address_confirm", intent="deny") == "address_input"
    assert cf.derive_awaiting("respond", "idle", "address_confirm", intent="address_change") == "address_input"


def test_N1_maps_to_quantity():
    # 승인 결정(후보 B): N1 "몇 개 필요하세요?" = product_confirming 에서 확정했으나
    # 수량이 없어 되묻는 상태 → awaiting=quantity. (수량이 있었으면 router 가
    # payment_agent 로 보내 이 폴백에 도달하지 않는다.)
    assert cf.derive_awaiting("product_agent", "product_confirming", "product_confirm", intent="confirm") == "quantity"
    assert cf.derive_awaiting("respond", "product_confirming", None, intent="confirm") == "quantity"
    assert "quantity" in cf.AWAITING_VALUES


def test_N2_N3_are_intentionally_unmapped():
    # 승인 결정(후보 B): N2("이 상품으로 주문할까요?") / N3("결제를 계속 진행할까요?")
    # 는 정상 경로에 이미 대응 pending_type(product_confirm / payment sub-steps)이
    # 있고, 이 두 지점은 그게 유실됐을 때만 도달하는 비정상 폴백이라 fact 화
    # 대상이 아니다. derive_awaiting 은 의도적으로 UNKNOWN 을 반환한다.
    # N2: product_confirming 폴백 (intent=confirm 아님 — 그건 N1)
    assert cf.derive_awaiting("respond", "product_confirming", None) == cf.AWAITING_UNKNOWN
    assert cf.derive_awaiting("respond", "product_confirming", None, intent="ask") == cf.AWAITING_UNKNOWN
    # N3: payment_processing 폴백 (세부 pending 없음)
    assert cf.derive_awaiting("respond", "payment_processing", None) == cf.AWAITING_UNKNOWN


# ──────────────────────────────────────────────────────────────────────────
# 취소 흐름 (C1–C4)
# ──────────────────────────────────────────────────────────────────────────

def test_C1_ask_what_to_buy():
    bundle = cf.build_bundle(cf.derive_awaiting("", "cart_shopping", "what_to_buy"))
    assert bundle == b("what_to_buy")


def test_C2_cancel_node_ignores_wrong_pending_type():
    # WON-26 §5-6: cancel_node 가 pending_action.type 을 "payment_confirm" 으로
    # 잘못 남긴다. last_agent=="cancel" 이면 type 을 아예 보지 않아야 한다.
    bundle = cf.build_bundle(
        cf.derive_awaiting("cancel", "idle", "payment_confirm"),
        cf.cart_cleared("cancel"),
    )
    assert bundle == b("none", {"fact_type": "cart_cleared", "reason": "cancel"})
    # type 을 순진하게 믿었으면 order_complete 로 샜을 것
    assert cf._BY_PENDING["payment_confirm"] == "order_complete"


def test_C3_cancel_confirmation_declined():
    assert cf.derive_awaiting("cancel_confirmation", "idle", "cancel_declined") == "none"


def test_C4_cancel_confirmation_prompt():
    bundle = cf.build_bundle(
        cf.derive_awaiting("cancel_confirmation", "cart_shopping", "cancel_confirm"),
        cf.cancel_empties_cart(),
    )
    assert bundle == b("cancel_confirm", {"fact_type": "cancel_empties_cart"})


# ──────────────────────────────────────────────────────────────────────────
# 값 정규화 (Task 1 §3-E) — WON-26 §5-2 재현
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [None, 0, -3, "0", "  ", "abc", False])
def test_quantity_none_or_bad_is_normalized_to_one(raw):
    assert cf.single_item(["딸기"], "설향 딸기 500g", raw, 10000) == {
        "fact_type": "single_item", "label": "딸기", "quantity": 1, "total_krw": 10000,
    }
    assert cf.item_just_added(["딸기"], None, raw)["quantity"] == 1


def test_quantity_korean_numeral_and_digit_string():
    assert cf.single_item(["딸기"], None, "두", 1000)["quantity"] == 2
    assert cf.single_item(["딸기"], None, "3개", 1000)["quantity"] == 3
    assert cf.item_just_added(["딸기"], None, 5)["quantity"] == 5


def test_cart_contents_normalizes_broken_rows():
    cart = [
        {"keywords": [], "product_name": "설향 딸기 500g", "quantity": None, "total": None},
        {"keywords": ["우유"], "product_name": "", "quantity": "2", "total": "5,600"},
    ]
    fact = cf.cart_contents(cart)
    assert fact == {
        "fact_type": "cart_contents", "item_count": 2, "total_krw": 5600,
        "items": [
            {"label": "설향 딸기 500g", "quantity": 1},
            {"label": "우유", "quantity": 2},
        ],
    }


def test_label_fallback_chain():
    assert cf.single_item([], None, 1, 0)["label"] == "상품"
    assert cf.single_item([""], "이름있음", 1, 0)["label"] == "이름있음"
    assert cf.single_item(["부름"], "이름있음", 1, 0)["label"] == "부름"


def test_empty_address_becomes_no_address_fact():
    assert cf.address_on_file({}) == {"fact_type": "no_address_on_file"}
    assert cf.address_on_file(None) == {"fact_type": "no_address_on_file"}
    assert cf.address_on_file({"address_line1": "", "address_line2": ""}) == {"fact_type": "no_address_on_file"}
    assert cf.address_selected({"address_line1": "  "}) == {"fact_type": "no_address_on_file"}


def test_address_selected_short_form():
    addr = {"address_line1": "서울특별시 송파구 올림픽로 300", "address_line2": "201호"}
    assert cf.address_selected(addr)["address"] == "서울특별시 송파구 올림픽로..."
    short = {"address_line1": "마포구 100", "address_line2": ""}
    assert cf.address_selected(short)["address"] == "마포구 100"


# ──────────────────────────────────────────────────────────────────────────
# delivery timing 단일화 (Task 1 §3-D) — WON-26 §5-1 재현
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("info,timing,raw", [
    ("샛별배송", "next_morning_7am", None),
    ("새벽배송", "next_morning_7am", None),   # _delivery_msg 는 "새벽" 을 못 잡았음 → 이제 통일
    ("로켓배송", "next_day", None),
    ("당일배송", "same_day", None),
    ("2일 후 도착", "two_days", None),         # _delivery_msg 는 "2일" 을 못 잡았음
    ("일반배송", "unknown", "일반배송"),
    ("내일 도착", "unknown", "내일 도착"),
    ("", "unknown", None),
    (None, "unknown", None),
])
def test_delivery_estimate_unified_rule(info, timing, raw):
    assert cf.delivery_estimate(info, 0) == {
        "fact_type": "delivery_estimate", "timing": timing,
        "raw_delivery_text": raw, "fee_krw": 0,
    }


def test_delivery_fee_normalization():
    assert cf.delivery_estimate("로켓배송", None)["fee_krw"] == 0
    assert cf.delivery_estimate("일반배송", 3000)["fee_krw"] == 3000
    assert cf.delivery_estimate("일반배송", "2,500")["fee_krw"] == 2500


# ──────────────────────────────────────────────────────────────────────────
# payment_method 표기 통일 (§5-4) / unanswerable 분리 (§5-3) / error 구분 (§5-5)
# ──────────────────────────────────────────────────────────────────────────

def test_payment_method_is_always_naverpay():
    assert cf.payment_method() == {"fact_type": "payment_method", "method": "네이버페이"}


def test_unanswerable_topic_hint_clamped_and_no_prefix():
    assert cf.unanswerable("delivery") == {"fact_type": "unanswerable", "topic_hint": "delivery"}
    assert cf.unanswerable("payment_method")["topic_hint"] == "payment_method"
    assert cf.unanswerable("환불정책")["topic_hint"] is None      # 목록 밖 → None
    assert cf.unanswerable()["topic_hint"] is None


def test_payment_error_kind_split():
    assert cf.payment_error("idempotency_conflict")["kind"] == "idempotency_conflict"
    assert cf.payment_error("execution_error")["kind"] == "execution_error"
    assert cf.payment_error("something_else")["kind"] == "execution_error"   # 미지값 → execution_error

    class IdempotencyConflictError(Exception):
        pass

    assert cf.payment_error_from_exc(IdempotencyConflictError("x"))["kind"] == "idempotency_conflict"
    assert cf.payment_error_from_exc(RuntimeError("x"))["kind"] == "execution_error"


# ──────────────────────────────────────────────────────────────────────────
# 결정론 + 커버리지
# ──────────────────────────────────────────────────────────────────────────

def test_extraction_is_deterministic():
    cart = [{"keywords": ["딸기"], "product_name": "설향 딸기 500g", "quantity": 2, "total": 25800}]
    make = lambda: cf.build_bundle(
        cf.derive_awaiting("payment_agent", "payment_processing", "payment_method_confirm"),
        cf.cart_contents(cart),
        cf.payment_method(),
        cf.delivery_estimate("로켓배송", 0),
    )
    assert make() == make()
    import json
    assert json.dumps(make(), sort_keys=True, ensure_ascii=False) == json.dumps(make(), sort_keys=True, ensure_ascii=False)


def test_all_mapped_awaiting_values_are_in_schema():
    combos = [
        ("payment_agent", "cart_shopping", "continue_shopping", None),
        ("payment_agent", "cart_shopping", "cart_review", None),
        ("payment_agent", "cart_shopping", "what_to_buy", None),
        ("payment_agent", "cart_shopping", "address_required", None),
        ("payment_agent", "payment_processing", "address_confirm", None),
        ("payment_agent", "payment_processing", "payment_method_confirm", None),
        ("payment_agent", "payment_processing", "payment_password", None),
        ("payment_agent", "payment_processing", "payment_retry_confirm", None),
        ("payment_agent", "completed", "payment_confirm", None),
        ("payment_agent", "idle", "clarification", None),
        ("cancel", "idle", "payment_confirm", None),
        ("cancel_confirmation", "x", "cancel_declined", None),
        ("cancel_confirmation", "x", "cancel_confirm", None),
        ("response_agent", "idle", "address_confirm", "ask"),
        ("respond", "idle", "address_confirm", "confirm"),
        ("respond", "idle", "address_confirm", "deny"),
        ("respond", "failed", None, None),
        ("respond", "completed", None, None),
        ("product_agent", "product_confirming", "product_confirm", "confirm"),  # N1
    ]
    for la, st, pt, it in combos:
        got = cf.derive_awaiting(la, st, pt, intent=it)
        assert got != cf.AWAITING_UNKNOWN, (la, st, pt, it)
        assert got in cf.AWAITING_VALUES, got


def test_emitted_fact_types_match_task1_schema():
    emitted = {
        cf.cart_contents([])["fact_type"],
        cf.single_item([], None, 1, 0)["fact_type"],
        cf.cart_empty()["fact_type"],
        cf.item_just_added([], None, 1)["fact_type"],
        cf.address_on_file({"address_line1": "x"})["fact_type"],
        cf.address_selected({"address_line1": "x"})["fact_type"],
        cf.no_address_on_file()["fact_type"],
        cf.payment_method()["fact_type"],
        cf.delivery_estimate("로켓", 0)["fact_type"],
        cf.order_placed("o")["fact_type"],
        cf.payment_error("execution_error")["fact_type"],
        cf.selection_rechecking()["fact_type"],
        cf.no_product_to_pay()["fact_type"],
        cf.cart_cleared()["fact_type"],
        cf.cancel_empties_cart()["fact_type"],
        cf.unanswerable()["fact_type"],
    }
    assert emitted == {
        "cart_contents", "single_item", "cart_empty", "item_just_added",
        "address_on_file", "address_selected", "no_address_on_file",
        "payment_method", "delivery_estimate", "order_placed", "payment_error",
        "selection_rechecking", "no_product_to_pay", "cart_cleared",
        "cancel_empties_cart", "unanswerable",
    }

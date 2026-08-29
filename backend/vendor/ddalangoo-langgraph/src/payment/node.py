"""
Payment Agent Node.

결제 단계 (모두 mock):
  1. 상품 확인 → mock_add_to_cart → 장바구니 안내
  2. 결제 시작 → mock_get_cart → 총액 + 결제수단 확인
  3. 결제수단 확인 → 배송지 확인
  4. 배송지 확인 → 비밀번호 요청
  5. 비밀번호 입력 → mock_place_order → 완료

파일명: 예전엔 payment/subgraph.py였는데, 실제로는 LangGraph subgraph가
아니라 ShoppingState를 직접 받는 플랫 노드 함수라 이름이 실제 역할과
안 맞았다 — payment/node.py로 정리했다.

한때 Payment를 Subgraph로 분리하려던 시도(PaymentState, payment_flow(),
bridge_shopping_to_payment/bridge_payment_to_shopping)가 있었지만 실제
그래프에 연결된 적이 없고, selected_product가 단수라 장바구니(다중 상품)
지원과도 안 맞아 제거했다 — 필요해지면 장바구니 지원을 포함해 다시
설계해야 한다.
"""
import re
import uuid
from typing import Any, Optional
from src.state.schema import ShoppingState
from src.state.node_inputs import PaymentAgentInput, PaymentAgentUpdate
from src.utils.agent_logger import agent_logger, _ptype
from src.agents.product_agent import validate_selected_product
from src.tools import db_client
from src.utils import commerce_facts as cf
from src.utils import commerce_voice
from src.tools.mock_tools import (
    mock_add_to_cart,
    mock_get_cart,
    mock_clear_cart,
    mock_place_order,
    mock_get_default_address,
    IdempotencyConflictError,
)

_KR_NUMBERS = {
    "하나": 1, "한": 1, "일": 1,
    "둘": 2, "두": 2,
    "셋": 3, "세": 3,
    "넷": 4, "네": 4,
    "다섯": 5, "오": 5,
    "여섯": 6, "육": 6,
    "일곱": 7, "칠": 7,
    "여덟": 8, "팔": 8,
    "아홉": 9, "구": 9,
    "열": 10, "십": 10,
}


def _coerce_positive_int(value, default=None):
    if value is None:
        return default
    if isinstance(value, int):
        return value if value > 0 else default
    text = str(value).strip()
    m = re.search(r"\d+", text.replace(",", ""))
    if m:
        parsed = int(m.group())
        return parsed if parsed > 0 else default
    for token, number in sorted(_KR_NUMBERS.items(), key=lambda x: -len(x[0])):
        if token in text:
            return number
    return default


def _build_delivery_address(state: ShoppingState) -> dict:
    address_text = state.get("address_text")
    if address_text:
        return {"address_line1": address_text, "address_line2": "", "recipient_name": "고객", "recipient_phone": "", "zip_code": ""}
    return mock_get_default_address(state.get("user_id", "")) or {}


def _format_address(address: dict) -> str:
    addr1 = address.get("address_line1", "")
    addr2 = address.get("address_line2", "")
    return f"{addr1} {addr2}".strip() if addr2 else addr1


def _short_address(addr: str) -> str:
    parts = addr.split()
    return " ".join(parts[:3]) + "..." if len(parts) > 3 else addr


def _require_address(state: ShoppingState) -> Optional[PaymentAgentUpdate]:
    """무주소면 결제를 진행시키지 않고 cart_shopping으로 되돌리는 업데이트를 반환한다
    (주소가 있으면 None). WON-29 RC-3 — 배송지 가드가 Step 1-5에만 있어서
    address_confirm / payment_method_confirm / payment_password 단계에선 무주소로도
    결제 후반부까지 진행되고 빈 주소로 주문이 나가던 문제. 각 단계 공통 방어선."""
    if _format_address(_build_delivery_address(state)):
        return None
    return {
        "stage": "cart_shopping",
        "error": "address_required",
        "last_agent": "payment_agent",
        "pending_action": {
            "type": "address_required",
            "message": "아직 등록된 배송지가 없으시네요. 배송지를 먼저 알려주시겠어요?",
            "payload": {"subType": "address_required"},
        },
    }


def _save_address_from_utterance(state: ShoppingState) -> Optional[str]:
    """이번 턴에 새 주소를 말했으면(intent=address_change + address_text) 저장하고
    표시용 짧은 주소를 반환한다. 저장할 게 없으면 None. WON-29 RC-2 — 사용자가
    새 주소를 말해도 어디에도 저장하지 않던 문제(db_client에 저장 함수 자체가 없었음)."""
    if state.get("intent") != "address_change" or not state.get("address_text"):
        return None
    address = _build_delivery_address(state)
    db_client.save_default_address(state.get("user_id", ""), address)
    return _short_address(_format_address(address))


def _item_matches_keyword(item: dict, keyword: str) -> bool:
    """product_name은 검색 결과 그대로라 사용자가 부른 말과 다를 수 있다(예: "계란" vs
    "유정란") — 담을 때 같이 저장해둔 item 자체의 keywords(사용자가 실제로 뭐라고
    불렀는지)도 함께 비교한다. fl-2026-08-18-006에서 확인된 패턴 그대로."""
    if not keyword:
        return False
    name = item.get("product_name", "") or ""
    item_keywords = item.get("keywords") or []
    return keyword in name or any(keyword in ik or ik in keyword for ik in item_keywords)


def _cart_row(product: dict, quantity: int, keywords: Optional[list[str]]) -> dict[str, Any]:
    return {
        "product_name": product.get("product_name", "상품"),
        "price": product.get("price", 0),
        "quantity": quantity,
        "platform": product.get("platform", ""),
        "product_url": product.get("product_url", ""),
        "product": product,
        "keywords": keywords or [],
    }


def _apply_cart_operations(
    user_id: str,
    operations: list[dict[str, Any]],
    new_item: Optional[tuple[dict, int, list[str]]] = None,
) -> list[dict[str, Any]]:
    """intent_agent가 만든 CartOperation[]을 현재 장바구니(+ 있으면 이번 턴에 새로
    확인된 상품)에 순서대로 적용한다. LLM은 발화를 구조화된 operation으로 변환하는
    파서 역할만 하고, 실제 수량 계산/커밋은 여기 deterministic 코드가 전담한다
    (Parser(LLM) -> Operation -> Reducer(코드) 분리, fl-2026-08-25-001).

    CLEAR_CART는 그 시점까지 쌓인 장바구니를 통째로 비운다 — 뒤따르는 operation은
    빈 장바구니 위에 적용된다("다 빼고 X만" = [CLEAR_CART, SET_QUANTITY(X, ...)]).
    CLEAR_CART로 지워진 뒤에도 원래 장바구니에 있던 품목이나 이번 턴에 확인 중인
    상품(new_item)이 다시 지목되면, mock_get_cart만으론 이미 지워졌으니 별도로
    들고 있는 원본 product 데이터(revival_pool)로 되살아난다.

    revival_pool에도 없는 품목을 겨냥한 operation(한 번도 검색된 적 없는 완전히
    새 품목, 예: "싹 다 비우고 계란/참기름만 담아")은 여기서 처리할 수 없다 —
    실제 상품 정보(가격/URL)가 없어 채울 수 없고 별도 상품 검색이 필요하다.
    호출부가 그 검색을 이어서 시작할 수 있도록 unresolved 목록을 반환한다
    (fl-2026-08-25-001 잔여 케이스, purchase_queue_agent로 이어붙임)."""
    original_cart = [dict(row) for row in mock_get_cart(user_id)]
    working: list[dict[str, Any]] = list(original_cart)
    revival_pool: list[dict[str, Any]] = list(original_cart)
    if new_item:
        product, qty, kws = new_item
        new_row = _cart_row(product, qty, kws)
        working.append(new_row)
        revival_pool.append(new_row)

    unresolved: list[dict[str, Any]] = []
    for op in operations:
        kind = op.get("op")
        if kind == "CLEAR_CART":
            working = []
            continue

        item_kw = op.get("item") or ""
        idx = next((i for i, row in enumerate(working) if _item_matches_keyword(row, item_kw)), None)
        if idx is None:
            revived = next((row for row in revival_pool if _item_matches_keyword(row, item_kw)), None)
            if revived is not None:
                working.append(dict(revived))
                idx = len(working) - 1
        if idx is None:
            unresolved.append(op)
            continue

        row = working[idx]
        if kind == "REMOVE_ITEM":
            del working[idx]
        elif kind in ("SET_QUANTITY", "ADD_ITEM"):
            q = op.get("quantity")
            row["quantity"] = q if q and q > 0 else row.get("quantity", 1)
        elif kind == "CHANGE_QUANTITY":
            new_qty = row.get("quantity", 1) + (op.get("delta") or 0)
            # 0 이하로 줄이면 완전 제거(우유 2개뿐인데 3개 빼달라고 해도 음수로
            # 남기지 않고 그냥 다 뺀다).
            if new_qty > 0:
                row["quantity"] = new_qty
            else:
                del working[idx]

    # mock_add_to_cart는 병합이 아니라 append라, 동일 상품명이어도 그냥 새 줄로
    # 쌓인다 — 항상 전체를 비우고 다시 담는 clear+rebuild 패턴을 쓴다.
    mock_clear_cart(user_id)
    for row in working:
        mock_add_to_cart(user_id, row.get("product") or row, row.get("quantity", 1), row.get("keywords"))

    if unresolved:
        agent_logger.log(
            f"[payment_agent] cart_operations 중 기존 장바구니/이번 턴 확인 상품 어디와도 "
            f"매칭 안 돼 신규 검색 필요: {unresolved}"
        )
    return unresolved


def _extract_last_user_text(messages: Optional[list]) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, dict):
            content = msg.get("content")
            role = msg.get("role") or msg.get("type")
            if content and role in (None, "user", "human"):
                return str(content)
        else:
            content = getattr(msg, "content", None)
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
            if content and msg_type in (None, "human", "user"):
                return str(content)
    return ""


# WON-19 Unit 4: 결제 흐름 대기 중(address_confirm/payment_method_confirm/
# payment_password) 결제수단/배송 질문에 결정론적으로 답한다. Unit 3에서
# intent="ask"가 이 세 pending_type에서도 needs_clarification에 안 막히도록
# 넓혀뒀으니(그때는 여기 답변 로직이 없어 일부러 좁혀뒀었다), 이제 실제로
# payment_agent에 도달한다 — 대신 여기서 반드시 "질문에 답하고 원래
# pending_action을 그대로 유지"해야 한다(ADR-005, 결제는 human-in-the-loop).
_PAYMENT_METHOD_QUESTION_KEYWORDS = ("카드", "결제수단", "결제 수단", "결제방법", "결제 방법", "무통장", "계좌이체", "페이")
_DELIVERY_QUESTION_KEYWORDS = ("배송", "도착", "택배")
_PAYMENT_FLOW_ASK_PENDING_TYPES = frozenset({"address_confirm", "payment_method_confirm", "payment_password"})


def _payment_flow_question_fact(state: PaymentAgentInput) -> Optional[dict]:
    """결제 흐름 중 질문을, 이미 가진 mock 데이터로 답할 수 있으면 그 사실을
    fact 로 반환한다(배송=selected_product.delivery, 결제수단=naver_pay 하나).
    근거 없는 질문은 None → 호출부가 unanswerable fact 로 정직하게 처리."""
    user_text = _extract_last_user_text(state.get("messages"))
    if any(kw in user_text for kw in _DELIVERY_QUESTION_KEYWORDS):
        product = state.get("selected_product") or {}
        return cf.delivery_estimate(product.get("delivery", ""), product.get("delivery_fee"))
    if any(kw in user_text for kw in _PAYMENT_METHOD_QUESTION_KEYWORDS):
        return cf.payment_method()
    return None


def payment_agent_node(state: PaymentAgentInput) -> PaymentAgentUpdate:
    stage = state.get("stage")
    pending_type = (state.get("pending_action") or {}).get("type")
    user_id = state.get("user_id", "")

    selected_product = state.get("selected_product") or {}
    keywords = state.get("keywords") or []
    short_name = keywords[0] if keywords else selected_product.get("product_name", "상품")
    price = _coerce_positive_int(selected_product.get("price"), default=0) or 0
    quantity = _coerce_positive_int(state.get("quantity"), default=None)
    delivery_info = selected_product.get("delivery", "")

    total = price * (quantity or 1)

    intent = state.get("intent")
    _log_in = {"intent": intent, "pending_type": pending_type, "quantity": quantity, "stage": stage}

    # ── 결제 흐름 중 질문(결제수단/배송 등) — 진행시키지 않고 답한 뒤 원래
    # 대기 상태로 그대로 복귀한다(ADR-005, WON-19 Unit 4). Step 0~4 어느
    # 단계로도 진행하지 않도록 다른 모든 분기보다 먼저 처리한다.
    if intent == "ask" and pending_type in _PAYMENT_FLOW_ASK_PENDING_TYPES:
        # WON-33 Unit 3 — P2/P3/P4. 답할 수 있으면 그 사실을, 아니면 unanswerable
        # 을 fact 로 실어 render_voice 가 "답하고 원래 대기로 복귀"하는 문구를
        # 만든다(원래 pending 메시지를 접두어로 붙이지 않는다, WON-26 §5-3).
        q_fact = _payment_flow_question_fact(state) or cf.unanswerable(None)
        message = commerce_voice.render_voice(cf.build_bundle(
            cf.derive_awaiting("payment_agent", "payment_processing", pending_type),
            q_fact,
        ))
        output = {
            "pending_action": {"type": pending_type, "message": message},
            "error": None,
            "last_agent": "payment_agent",
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log(f"[payment_agent] 결제 흐름 질문 응답 | pending_type={pending_type} fact={q_fact['fact_type']}")
        return output

    # ── Step 0: 상품 확인 → 장바구니 담기 ──
    if (
        stage == "product_confirming"
        and pending_type == "product_confirm"
        and intent in ("confirm", "quantity_change")
    ):
        # WON-22 Unit 9 — 실제로 장바구니에 담기 전 마지막 재검증. product_
        # agent의 게이트(같은 이름의 validate_selected_product, product_agent.py)
        # 가 이미 한 번 통과시킨 상품이지만, 이 턴 사이 state가 다른 경로로
        # 바뀌었을 가능성까지 방어하는 독립된 최종 게이트다(완료 조건:
        # "Payment Agent까지 잘못된 제품이 전달되지 않음" — 단일 지점 신뢰
        # 금지, product_agent와 동일한 원칙).
        validation = validate_selected_product(selected_product, state.get("product_request"))
        if not validation.matches:
            agent_logger.log(
                f"[payment_agent] Unit 9 최종 검증 실패(selection_validation_failed) — "
                f"장바구니 담기 차단: {selected_product.get('product_name')!r} - {validation.mismatches}"
            )
            return {
                "stage": "idle",
                "error": "selection_validation_failed",
                "last_agent": "payment_agent",
                "selected_product": None,
                "pending_action": {
                    "type": "clarification",
                    # WON-33 Unit 3 — P6.
                    "message": commerce_voice.render_voice(cf.build_bundle(
                        cf.derive_awaiting("payment_agent", "idle", "clarification"),
                        cf.selection_rechecking(),
                    )),
                },
            }
        if state.get("queue_clear_existing"):
            # "싹 다 비우고 계란만 담아"류 요청 — CLEAR_CART 신호는 intent_agent가
            # 처음 판단한 턴에만 cart_operations에 있었고, 실제 담기가 실행되는
            # 이 확인 턴("네")엔 이미 비워져 있다. queue_clear_existing(턴을
            # 넘어 지속되는 필드)으로 전달받아 여기서 소비한다.
            mock_clear_cart(user_id)
        cart_operations = state.get("cart_operations") or []
        if cart_operations:
            # "다 빼고 서울우유 한 개만 결제해줘"처럼, 방금 확인한 상품을 담는
            # 동시에 기존 장바구니의 나머지 품목도 같이 조작하라는 요청
            # (fl-2026-08-25-001) — 지금 확인 중인 상품을 새 품목으로 얹은 뒤
            # cart_operations를 순서대로 적용한다.
            _apply_cart_operations(user_id, cart_operations, new_item=(selected_product, quantity or 1, keywords))
        else:
            mock_add_to_cart(user_id, selected_product, quantity, keywords)
        cart = mock_get_cart(user_id)
        # WON-33 Unit 3 — P7(다품목)/P8(단품). 방금 담은 품목 + 현재 장바구니를
        # fact 로 실어 "담았어요, 결제할까요/더 담을까요" 문구를 만든다.
        cart_msg = commerce_voice.render_voice(cf.build_bundle(
            cf.derive_awaiting("payment_agent", "cart_shopping", "continue_shopping"),
            cf.item_just_added(keywords, selected_product.get("product_name"), quantity),
            cf.cart_contents(cart) if len(cart) > 1 else cf.single_item(
                keywords, selected_product.get("product_name"), quantity, selected_product.get("price"),
            ),
        ))
        output = {
            "stage": "cart_shopping",
            "selected_product": selected_product,
            "cart_items": cart,
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {"type": "continue_shopping", "message": cart_msg},
            # 장바구니가 바뀌었으므로 새 결제 멱등성 키 발급 — 이전 키로
            # mock_place_order를 호출하면 IdempotencyConflictError가 나야 정상.
            "payment_idempotency_key": str(uuid.uuid4()),
            # 소비했으니 되돌린다 — 다음에 이 노드가 다시 불릴 때(전혀 다른
            # 상품 확인) 잘못 남아 또 비우는 일이 없도록.
            "queue_clear_existing": False,
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log(f"[payment_agent] Step 0 완료 | 장바구니 {len(cart)}개  총액 {sum(i['total'] for i in cart):,}원")
        return output

    # ── Step 1: 장바구니 최종 점검 (cart_review) ──
    if (stage == "cart_shopping" or pending_type is None) and pending_type != "cart_review":
        cart = mock_get_cart(user_id)
        if not cart and not selected_product:
            output = {
                "stage": "cart_shopping",
                "error": "payment_precheck_missing_product",
                "last_agent": "payment_agent",
                "pending_action": {
                    "type": "what_to_buy",
                    # WON-33 Unit 3 — P9.
                    "message": commerce_voice.render_voice(cf.build_bundle(
                        cf.derive_awaiting("payment_agent", "cart_shopping", "what_to_buy"),
                        cf.no_product_to_pay(),
                    )),
                },
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output

        cart = cart or []
        # WON-33 Unit 3 — P10(장바구니 있음)/P11(단품). 총액·품목을 fact 로.
        review_msg = commerce_voice.render_voice(cf.build_bundle(
            cf.derive_awaiting("payment_agent", "cart_shopping", "cart_review"),
            cf.cart_contents(cart) if cart else cf.single_item(
                keywords, selected_product.get("product_name"), quantity, selected_product.get("price"),
            ),
        ))

        output = {
            "stage": "cart_shopping",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {"type": "cart_review", "message": review_msg},
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log(f"[payment_agent] Step 1 완료 | 장바구니 점검 대기")
        return output

    # ── Step 1-5: cart_review 확인 → 결제수단 선택 ──
    if pending_type == "cart_review":
        if intent == "quantity_change":
            cart_operations = state.get("cart_operations") or []
            if cart_operations:
                # 품목별로 다른 조작이 섞였거나("딸기는 하나 더하고 우유는 2개
                # 뺄게") 나머지를 전부 지우라는 요청("다 빼고 X만", "싹 다
                # 비워줘") — 아래 단일-품목 quantity=0 로직으로는 표현이 안 돼
                # cart_operations 경로를 대신 쓴다(fl-2026-08-25-001).
                unresolved = _apply_cart_operations(user_id, cart_operations, new_item=None)
                unresolved_adds = [op for op in unresolved if op.get("op") == "ADD_ITEM"]
                if unresolved_adds:
                    # 조작(비우기 등)은 이미 반영됐지만, 한 번도 검색된 적 없는
                    # 신규 품목이 남아있다("싹 다 비우고 계란/참기름만 담아") —
                    # purchase_queue_agent로 이어붙인다. 첫 품목은 이번 턴 곧장
                    # 검색을 시작하고(Unit 4와 동일 패턴), queue_items에도
                    # 포함시켜(current_queue_index=0) advance_queue가 나중에
                    # "방금 담은 품목" 이름을 올바르게 찾도록 한다(fl-2026-08-26-001
                    # 에서 확인된 인덱싱 규칙).
                    queue_items = [
                        {"name": op["item"], "quantity": op.get("quantity") or 1, "unit": "개"}
                        for op in unresolved_adds
                    ]
                    output = {
                        "stage": "idle",
                        "intent": "buy",
                        "keywords": [queue_items[0]["name"]],
                        "quantity": queue_items[0]["quantity"],
                        "queue_items": queue_items,
                        "current_queue_index": 0,
                        "queue_source": "multi_buy",
                        "cart_items": mock_get_cart(user_id),
                        "error": None,
                        "last_agent": "payment_agent",
                        "payment_idempotency_key": str(uuid.uuid4()),
                    }
                    agent_logger.log_payment_agent(_log_in, output)
                    return output
                cart = mock_get_cart(user_id)
                # WON-33 Unit 3 — P12 (cart_operations 경로).
                review_pending = "cart_review" if cart else "what_to_buy"
                review_msg = commerce_voice.render_voice(cf.build_bundle(
                    cf.derive_awaiting("payment_agent", "cart_shopping", review_pending),
                    cf.cart_contents(cart) if cart else cf.cart_empty(),
                ))
                output = {
                    "stage": "cart_shopping",
                    "cart_items": cart,
                    "error": None,
                    "last_agent": "payment_agent",
                    "pending_action": {"type": review_pending, "message": review_msg},
                    "payment_idempotency_key": str(uuid.uuid4()),
                }
                agent_logger.log_payment_agent(_log_in, output)
                return output

            # 완전히 제거하려는 요청("계란은 빼줘")도 quantity_change로 분류되고
            # quantity=0으로 채워진다(intent_prompt.py 참고, fl-2026-08-18-006) —
            # 이 경우 대상 품목은 재담기 없이 완전히 뺀다.
            raw_qty = state.get("quantity")
            is_removal = raw_qty == 0
            new_qty = None if is_removal else _coerce_positive_int(raw_qty, default=quantity)
            if (new_qty or is_removal) and (keywords or selected_product):
                # 장바구니에 다른 상품이 더 있을 수 있으므로, 전체를 비우고
                # 대상 하나만 다시 담으면 무관한 다른 품목이 같이 사라진다
                # (실측 확인됨, fl-2026-08-18-005). 대상 품목만 갱신/제거하고
                # 나머지는 그대로 유지한다. 대상 식별은 이번 턴에 실제로 언급된
                # keywords를 우선하고(예: 계란을 말했는데 selected_product가
                # 이전 턴의 우유로 남아있는 경우 대비, fl-2026-08-18-006),
                # keywords가 없을 때만 selected_product로 보충한다.
                existing_cart = mock_get_cart(user_id)

                def _matches_target(item: dict) -> bool:
                    name = item.get("product_name", "") or ""
                    # product_name은 검색 결과 그대로라 사용자가 부른 말과 다를 수 있다
                    # (예: "계란" vs "유정란") — 담을 때 같이 저장해둔 item 자체의
                    # keywords(사용자가 실제로 뭐라고 불렀는지)도 함께 비교한다.
                    item_keywords = item.get("keywords") or []
                    if keywords:
                        return any(
                            kw and (kw in name or any(kw in ik or ik in kw for ik in item_keywords))
                            for kw in keywords
                        )
                    return selected_product is not None and name == selected_product.get("product_name")

                mock_clear_cart(user_id)
                matched = False
                for item in existing_cart:
                    if _matches_target(item):
                        matched = True
                        if not is_removal:
                            mock_add_to_cart(user_id, item.get("product") or selected_product, new_qty, item.get("keywords") or keywords)
                    else:
                        mock_add_to_cart(user_id, item.get("product") or item, item.get("quantity", 1), item.get("keywords"))
                if not matched and not is_removal and selected_product:
                    mock_add_to_cart(user_id, selected_product, new_qty, keywords)
            cart = mock_get_cart(user_id)
            # WON-33 Unit 3 — P12 (단일 품목 수량변경/제거 경로).
            review_pending = "cart_review" if cart else "what_to_buy"
            review_msg = commerce_voice.render_voice(cf.build_bundle(
                cf.derive_awaiting("payment_agent", "cart_shopping", review_pending),
                cf.cart_contents(cart) if cart else cf.cart_empty(),
            ))
            output = {
                "stage": "cart_shopping",
                "quantity": new_qty,
                "cart_items": cart,
                "error": None,
                "last_agent": "payment_agent",
                "pending_action": {"type": review_pending, "message": review_msg},
                # 장바구니가 바뀌었으므로 새 결제 멱등성 키 발급.
                "payment_idempotency_key": str(uuid.uuid4()),
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output

        guard = _require_address(state)
        if guard:
            agent_logger.log_payment_agent(_log_in, guard)
            return guard
        addr_display = _format_address(_build_delivery_address(state))
        output = {
            "stage": "payment_processing",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {"type": "address_confirm", "message": f"{_short_address(addr_display)}로 보낼게요. 맞으시죠?"},
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log(f"[payment_agent] Step 1-5 완료 | 배송지={addr_display}")
        return output

    # ── Step 2: 배송지 확인 → 결제수단 선택 ──
    if pending_type == "address_confirm":
        # 확인 대기 중 새 주소를 말하면(WON-29 RC-2) 저장하고 그 주소로 재확인한다.
        saved_short = _save_address_from_utterance(state)
        if saved_short is not None:
            output = {
                "stage": "payment_processing",
                "error": None,
                "last_agent": "payment_agent",
                "pending_action": {"type": "address_confirm", "message": f"{saved_short}로 보낼게요. 맞으시죠?"},
            }
            agent_logger.log_payment_agent(_log_in, output)
            agent_logger.log("[payment_agent] Step 2 | 새 배송지 저장 후 재확인")
            return output
        guard = _require_address(state)
        if guard:
            agent_logger.log_payment_agent(_log_in, guard)
            return guard
        cart = mock_get_cart(user_id)
        # WON-33 Unit 3 — P16(장바구니 있음)/P17(단품). 품목·총액 + 결제수단 fact.
        payment_msg = commerce_voice.render_voice(cf.build_bundle(
            cf.derive_awaiting("payment_agent", "payment_processing", "payment_method_confirm"),
            cf.cart_contents(cart) if cart else cf.single_item(
                keywords, selected_product.get("product_name"), quantity, selected_product.get("price"),
            ),
            cf.payment_method(),
        ))
        output = {
            "stage": "payment_processing",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {"type": "payment_method_confirm", "message": payment_msg},
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log(f"[payment_agent] Step 2 완료 | 결제수단 선택 대기")
        return output

    # ── Step 3: 결제수단 확인 → 비밀번호 요청 ──
    if pending_type == "payment_method_confirm":
        guard = _require_address(state)
        if guard:
            agent_logger.log_payment_agent(_log_in, guard)
            return guard
        output = {
            "stage": "payment_processing",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {
                "type": "payment_password",
                # WON-33 Unit 3 — P18.
                "message": commerce_voice.render_voice(cf.build_bundle(
                    cf.derive_awaiting("payment_agent", "payment_processing", "payment_password"),
                )),
            },
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log("[payment_agent] Step 3 완료 | 비밀번호 요청")
        return output

    # ── Step 4: 비밀번호 → mock 결제 실행 ──
    if pending_type == "payment_password":
        # 마지막 방어선 — 무주소 상태로 mock_place_order가 빈 주소로 실행되면 안 된다.
        guard = _require_address(state)
        if guard:
            agent_logger.log_payment_agent(_log_in, guard)
            return guard
        delivery_address = _build_delivery_address(state)
        # 정상 플로우라면 Step 0/1-5에서 이미 발급됐어야 하지만, 방어적으로
        # 없으면 여기서라도 생성한다 — 결제 실행 노드에 자동 Retry를 붙이지
        # 않는 대신(1-6 참고), 재시도/중복 요청은 이 키로 멱등하게 처리된다.
        idem_key = state.get("payment_idempotency_key") or str(uuid.uuid4())
        try:
            order = mock_place_order(
                user_id=user_id,
                delivery_address=delivery_address,
                payment_method="naver_pay",
                conversation_id=state.get("conversation_id"),
                idempotency_key=idem_key,
            )
        except IdempotencyConflictError as e:
            agent_logger.log(f"[payment_agent] 결제 멱등성 충돌: {e}")
            output = {
                # stage="failed"로 두면 after_respond()가 그래프를 바로 end해서
                # 사용자가 "다시 시도할까요?"에 답할 수 없다 — payment_processing을
                # 유지해 route()가 다음 턴에도 무조건 payment_agent로 되돌리게 한다.
                "stage": "payment_processing",
                "error": "payment_idempotency_conflict",
                "last_agent": "payment_agent",
                "pending_action": {
                    "type": "payment_retry_confirm",
                    # WON-33 Unit 2 — P19/P20 결제오류 문구를 commerce_voice로 생성.
                    "message": commerce_voice.render_voice(cf.build_bundle(
                        cf.derive_awaiting("payment_agent", "payment_processing", "payment_retry_confirm"),
                        cf.payment_error_from_exc(e),
                    )),
                },
                "payment_idempotency_key": None,
                "degraded_mode": True,
                "failure_stage": "payment_execute",
                "degradation_reason": type(e).__name__,
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output
        except Exception as e:
            agent_logger.log(f"[payment_agent] 주문 처리 오류: {e}")
            output = {
                "stage": "payment_processing",
                "error": "payment_failed",
                "last_agent": "payment_agent",
                "pending_action": {
                    "type": "payment_retry_confirm",
                    # WON-33 Unit 2 — P19/P20 결제오류 문구를 commerce_voice로 생성.
                    "message": commerce_voice.render_voice(cf.build_bundle(
                        cf.derive_awaiting("payment_agent", "payment_processing", "payment_retry_confirm"),
                        cf.payment_error_from_exc(e),
                    )),
                },
                "degraded_mode": True,
                "failure_stage": "payment_execute",
                "degradation_reason": type(e).__name__,
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output

        # WON-33 Unit 2 — P21 완료 문구를 commerce_voice로 생성(fact 번들 → 페르소나
        # 톤 문구, LLM 실패/비활성 시 결정론적 폴백).
        completion_msg = commerce_voice.render_voice(cf.build_bundle(
            cf.derive_awaiting("payment_agent", "completed", "payment_confirm"),
            cf.order_placed(order["order_id"]),
            cf.delivery_estimate(delivery_info),
        ))
        output = {
            "stage": "completed",
            "order_id": order["order_id"],
            "cart_items": [],
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {"type": "payment_confirm", "message": completion_msg},
            "storage_state_path": None,
            # 주문 완료 → 다음 결제 플로우엔 새 키가 발급돼야 하므로 비운다.
            "payment_idempotency_key": None,
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log(
            f"[payment_agent] Step 4 완료 | 주문 접수  "
            f"order_id={order['order_id']}  total={order['total']:,}원"
        )
        return output

    # fallback
    guard = _require_address(state)
    if guard:
        agent_logger.log_payment_agent(_log_in, guard)
        return guard
    output = {
        "stage": "payment_processing",
        "error": None,
        "last_agent": "payment_agent",
        "pending_action": {"type": "payment_method_confirm", "message": f"{short_name} {quantity}개, {total:,}원이에요. 네이버로 결제할까요?"},
    }
    agent_logger.log_payment_agent(_log_in, output)
    return output

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


def _delivery_msg(delivery_info: str) -> str:
    if "샛별" in delivery_info:
        return " 내일 아침 7시 전 도착이에요."
    if "로켓" in delivery_info:
        return " 내일 도착이에요."
    if "당일" in delivery_info:
        return " 오늘 도착이에요."
    return ""


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

    # ── Step 0: 상품 확인 → 장바구니 담기 ──
    if (
        stage == "product_confirming"
        and pending_type == "product_confirm"
        and intent in ("confirm", "quantity_change")
    ):
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
        if len(cart) > 1:
            cart_msg = f"{short_name}도 담았어요! 총 {len(cart)}가지예요. 결제할까요, 더 담을까요?"
        else:
            cart_msg = f"{short_name} {quantity}개 담았어요! 결제할까요, 다른 것도 보실래요?"
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
                "pending_action": {"type": "what_to_buy", "message": "상품을 아직 찾지 못했어요. 무엇을 구매하실까요?"},
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output

        cart = cart or []
        if cart:
            cart_total = sum(item["total"] for item in cart)
            items_summary = ", ".join(
                f"{(item.get('keywords') or [item.get('product_name', '상품')])[0]} {item.get('quantity', 1)}개"
                for item in cart
            )
            review_msg = f"총 {cart_total:,}원이에요. 수량을 바꾸거나 빼고 싶은 게 있으면 편하게 말씀해 주세요."
        else:
            review_msg = f"{short_name} {quantity or 1}개, {total:,}원이에요. 수량을 바꾸거나 빼고 싶은 게 있으면 편하게 말씀해 주세요."

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
                cart_total = sum(item["total"] for item in cart) if cart else 0
                review_msg = (
                    f"총 {cart_total:,}원이에요. 수량을 바꾸거나 빼고 싶은 게 있으면 편하게 말씀해 주세요."
                    if cart else "장바구니가 비었어요. 더 담으실래요?"
                )
                output = {
                    "stage": "cart_shopping",
                    "cart_items": cart,
                    "error": None,
                    "last_agent": "payment_agent",
                    "pending_action": {"type": "cart_review" if cart else "what_to_buy", "message": review_msg},
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
            cart_total = sum(item["total"] for item in cart) if cart else total
            items_summary = ", ".join(
                f"{(item.get('keywords') or [item.get('product_name', '상품')])[0]} {item.get('quantity', 1)}개"
                for item in cart
            ) if cart else (f"{short_name} {new_qty}개" if new_qty else "")
            review_msg = (
                f"총 {cart_total:,}원이에요. 수량을 바꾸거나 빼고 싶은 게 있으면 편하게 말씀해 주세요."
                if cart else "장바구니가 비었어요. 더 담으실래요?"
            )
            output = {
                "stage": "cart_shopping",
                "quantity": new_qty,
                "cart_items": cart,
                "error": None,
                "last_agent": "payment_agent",
                "pending_action": {"type": "cart_review" if cart else "what_to_buy", "message": review_msg},
                # 장바구니가 바뀌었으므로 새 결제 멱등성 키 발급.
                "payment_idempotency_key": str(uuid.uuid4()),
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output

        address = _build_delivery_address(state)
        addr_display = _format_address(address)
        if not addr_display:
            output = {
                "stage": "cart_shopping",
                "error": "address_required",
                "last_agent": "payment_agent",
                "pending_action": {"type": "address_required", "message": "아직 등록된 배송지가 없으시네요. 배송지를 먼저 알려주시겠어요?", "payload": {"subType": "address_required"}},
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output
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
        cart = mock_get_cart(user_id)
        if cart:
            cart_total = sum(item["total"] for item in cart)
            items_summary = ", ".join(
                f"{(item.get('keywords') or [item.get('product_name', '상품')])[0]} {item.get('quantity', 1)}개"
                for item in cart
            )
            payment_msg = f"{items_summary}, 총 {cart_total:,}원이에요. 네이버로 결제할까요?"
        else:
            payment_msg = f"{short_name} {quantity or 1}개, {total:,}원이에요. 네이버로 결제할까요?"
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
        output = {
            "stage": "payment_processing",
            "error": None,
            "last_agent": "payment_agent",
            "pending_action": {"type": "payment_password", "message": "결제 비밀번호를 입력해 주시겠어요?"},
        }
        agent_logger.log_payment_agent(_log_in, output)
        agent_logger.log("[payment_agent] Step 3 완료 | 비밀번호 요청")
        return output

    # ── Step 4: 비밀번호 → mock 결제 실행 ──
    if pending_type == "payment_password":
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
                    "message": "결제 처리 중에 문제가 있었어요. 죄송해요, 다시 시도해 볼까요?",
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
                    "message": "결제 처리 중에 문제가 있었어요. 죄송해요, 다시 시도해 볼까요?",
                },
                "degraded_mode": True,
                "failure_stage": "payment_execute",
                "degradation_reason": type(e).__name__,
            }
            agent_logger.log_payment_agent(_log_in, output)
            return output

        arrival = _delivery_msg(delivery_info)
        completion_msg = f"완료!{arrival}" if arrival else "완료! 주문이 접수됐어요."
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
    output = {
        "stage": "payment_processing",
        "error": None,
        "last_agent": "payment_agent",
        "pending_action": {"type": "payment_method_confirm", "message": f"{short_name} {quantity}개, {total:,}원이에요. 네이버로 결제할까요?"},
    }
    agent_logger.log_payment_agent(_log_in, output)
    return output

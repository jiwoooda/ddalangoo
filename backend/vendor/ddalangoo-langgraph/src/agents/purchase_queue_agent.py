"""
Purchase Queue Agent.

역할: 여러 품목을 순서대로 검색→확인→담기 반복하는 실행기. recipe_agent의
Mode 3(현재 품목 확정→쇼핑 시작)/Mode 4(담기 후 다음 품목 안내)를 그대로
옮겨왔다 — 조건/메시지 100% 동일, `queue_items`/`current_queue_index` 필드명만
쓴다(recipe_dish를 참조하지 않는 범용 실행기로 분리하는 게 목적, 설계 문서:
C:\\Users\\82108\\.claude\\plans\\radiant-questing-map.md).

Unit 2: 독립 그래프 노드로 승격됨. `route()`의 `_route_recipe_planning`
(intent=confirm)과 `after_payment_agent`(장바구니 담기 후 자동 진입)가 이제
recipe_agent 대신 이 노드로 직접 온다 — recipe_agent는 재료 추론/편집(Mode
1/2)만 담당한다.

Unit 3: `queue_source`("recipe" | "multi_buy")로 완료 문구만 분기한다 —
recipe_dish는 절대 참조하지 않는다. 이 큐가 레시피에서 왔는지 다중구매
요청에서 왔는지, 이 노드는 몰라도 된다(출처를 아는 쪽이 queue_source를
채워서 알려준다).
"""
from typing import Any

from src.state.schema import ShoppingState
from src.state.node_inputs import PurchaseQueueAgentInput, PurchaseQueueAgentUpdate
from src.utils.agent_logger import agent_logger

# WON-22 Unit 10 — queue_items의 각 원소를 ProductRequest와 연결한다. 기존
# 문자열 기반 shape({"name","quantity","unit"} — recipe_agent Mode 1이
# 아직도 이 shape만 채움)은 그대로 두고, "request"/"resolution_status"를
# 선택적으로 얹는다. request가 없는(구버전/레시피 출처) 품목은 여기서
# category 전용 ProductRequest로 즉석 변환해 하위 호환을 보장한다 — 품목별로
# 독립된 dict라서 한 품목의 request가 다른 품목 request를 오염시킬 수 없다
# (완료 조건: "한 품목 실패가 다른 품목 identity를 오염시키지 않게 처리").
def _normalize_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized.setdefault("unit", "개")
    normalized.setdefault("resolution_status", "pending")
    if not normalized.get("request"):
        normalized["request"] = {
            "category": normalized.get("name"),
            "brand": None,
            "product_name": None,
            "variant": None,
            "size": None,
            "size_preference": None,
            "quantity": normalized.get("quantity"),
            "platform": None,
            "excluded_brands": [],
            "condition": None,
            "match_mode": "category",
            "allow_substitution": False,
            "substitution_scope": [],
        }
    return normalized


def advance_queue(state: ShoppingState) -> dict:
    """Mode 4 — payment_agent 장바구니 담기 후 자동 진입, 다음 품목 안내 or 전체 완료.

    recipe_agent.py의 원래 Mode 4(L100-136)를 그대로 옮김. 완료 문구는
    `queue_source`로만 분기한다("recipe"면 "재료", 그 외엔 범용 문구) —
    recipe_dish는 절대 참조하지 않는다(이 노드는 이 큐가 레시피에서 왔는지
    모르는 게 원칙, 설계 문서 참고).
    """
    queue_items = [_normalize_queue_item(i) for i in (state.get("queue_items") or [])]
    current_idx = state.get("current_queue_index") or 0
    next_idx = current_idx + 1
    is_recipe = state.get("queue_source") == "recipe"

    # WON-22 Unit 10 — 이 노드가 불렸다는 건 payment_agent Step 0가 방금
    # current_idx 품목을 장바구니에 담는 데 성공했다는 뜻(after_payment_agent
    # 가 성공 시에만 여기로 체이닝) — 그 사실을 기록에 남긴다. 이 갱신은
    # current_idx 품목 하나의 dict만 바꾸므로 다른 품목의 request는 전혀
    # 안 건드린다(오염 방지).
    if current_idx < len(queue_items):
        queue_items[current_idx] = {**queue_items[current_idx], "resolution_status": "selected"}

    if next_idx >= len(queue_items):
        output = {
            "queue_items": queue_items,
            "current_queue_index": next_idx,
            "stage": "cart_shopping",
            "keywords": [],
            "quantity": None,
            "pending_action": {
                "type": "continue_shopping",
                "message": "모든 재료를 담았어요! 결제하실까요?" if is_recipe else "다 담았어요! 결제하실까요?",
            },
            "last_agent": "purchase_queue_agent",
            "error": None,
        }
    else:
        current_item = queue_items[current_idx]
        next_item = queue_items[next_idx]
        output = {
            "queue_items": queue_items,
            "current_queue_index": next_idx,
            "stage": "recipe_planning",
            "keywords": [],
            "quantity": None,
            "pending_action": {
                "type": "ingredient_confirm",
                "message": (
                    f"{current_item['name']} 담았어요! "
                    f"다음은 {next_item['name']} {next_item['quantity']}{next_item['unit']}이에요. "
                    f"찾아볼까요?"
                ),
            },
            "last_agent": "purchase_queue_agent",
            "error": None,
        }
    return output


def start_queue_item(state: ShoppingState) -> dict:
    """Mode 3 — 현재 품목 확정 → 쇼핑 시작(keywords/quantity 세팅 → context_agent 진입).

    recipe_agent.py의 원래 Mode 3(L139-150)를 그대로 옮김.
    """
    queue_items = [_normalize_queue_item(i) for i in (state.get("queue_items") or [])]
    current_idx = state.get("current_queue_index") or 0
    item = queue_items[current_idx]
    return {
        "queue_items": queue_items,
        "intent": "buy",
        "keywords": [item["name"]],
        "quantity": item.get("quantity"),
        # WON-22 Unit 10 — 품목별 ProductRequest를 그대로 실어서 product_agent
        # (Unit 4 하드 필터/Unit 5 ProductResolver/Unit 9 검증 게이트)가 이
        # 품목에도 keywords 기반 검색과 동일하게 적용되게 한다. 대부분의 큐
        # 품목(레시피 재료 등)은 category 전용이라 사실상 지금까지의 동작과
        # 같지만, 앞으로 품목별 브랜드/옵션이 채워지는 경로가 생기면 그대로
        # 활용된다.
        "product_request": item.get("request"),
        "stage": "idle",
        "last_agent": "purchase_queue_agent",
        "error": None,
    }


def purchase_queue_agent_node(state: PurchaseQueueAgentInput) -> PurchaseQueueAgentUpdate:
    """그래프 노드 진입점 — 도달 경로에 따라 Mode 3/4 중 하나로 분기한다.

    - `after_payment_agent`가 보낸 경우: stage="cart_shopping" (담기 직후, 다음
      품목 안내) → advance_queue.
    - `route()`의 `_route_recipe_planning`이 보낸 경우: stage="recipe_planning"
      + intent="confirm" (현재 품목 확정) → start_queue_item.
    """
    stage = state.get("stage")
    intent = state.get("intent")

    if stage == "cart_shopping" and state.get("queue_items"):
        output = advance_queue(state)
        agent_logger.log(f"[purchase_queue_agent] Mode 4 | {output['pending_action']['message']}")
        return output

    if stage == "recipe_planning" and intent == "confirm" and state.get("queue_items"):
        output = start_queue_item(state)
        agent_logger.log(f"[purchase_queue_agent] Mode 3 | {output['keywords'][0]} 쇼핑 시작")
        return output

    # route()/after_payment_agent가 queue_items 존재를 이미 확인하고 보내므로
    # 정상 흐름에서는 도달하지 않는다 — 방어적 fallback만 남긴다.
    agent_logger.log(f"[purchase_queue_agent] 예상치 못한 상태로 진입 | stage={stage} intent={intent}")
    return {
        "stage": "idle",
        "error": "purchase_queue_invalid_state",
        "last_agent": "purchase_queue_agent",
    }

"""
Recipe Agent Node.

역할:
  Mode 1 - 재료 목록 생성: 요리명+인원수 → LLM structured output → ingredient_confirm
  Mode 2 - 재료 제거 편집: 사용자가 특정 재료 제외 요청 → 목록 업데이트 후 재확인

Mode 3(쇼핑 시작)/Mode 4(다음 재료 안내)는 purchase_queue_agent.py로 완전히
이동했다(recipe_dish에 의존하지 않는 범용 실행기로 분리, Unit 2 — 독립 그래프
노드로 승격돼 route()/after_payment_agent가 recipe_agent를 거치지 않고 직접
그쪽으로 보낸다).

recipe_items/current_recipe_item_index 필드는 Unit 3에서 완전히 은퇴시켰다 —
Unit 1~2 과도기엔 queue_items와 나란히 채웠지만, current_recipe_item_index는
아무도 안 읽었고 recipe_items를 읽는 곳(recipe_agent 자신의 Mode 2 판단,
router.py의 Mode 1 진입 가드) 둘 다 queue_items로 바꿔도 그만이라 두 벌 유지할
이유가 없었다. 지금은 recipe_agent가 queue_items/current_queue_index를
직접 채운다 — queue_source="recipe"로 이 큐의 출처만 명시하고, recipe_dish는
purchase_queue_agent에 절대 넘기지 않는다(그쪽은 recipe 개념을 몰라야 함).
"""
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from configs.llm_config import get_llm
from src.state.schema import ShoppingState
from src.state.node_inputs import RecipeAgentInput, RecipeAgentUpdate
from src.prompts.recipe_prompt import RECIPE_GENERATE_PROMPT
from src.utils.agent_logger import agent_logger
from src.utils.retry import classify_failure, retry_call


class RecipeItem(BaseModel):
    name: str = Field(description="재료명 (예: 된장, 두부, 애호박)")
    quantity: int = Field(description="필요 수량 (양의 정수)")
    unit: str = Field(description="단위 (개, 통, 모, 단, g 등)")


class RecipeOutput(BaseModel):
    items: list[RecipeItem] = Field(description="주요 재료 목록 5~7가지")


_llm = None
_structured_llm = None


def _get_llm():
    global _llm, _structured_llm
    if _llm is None:
        # retry_owner="application": _generate_items가 retry_call()로 이 호출을
        # 감싸므로 SDK 자체 재시도는 꺼서 중첩 재시도를 막는다.
        _llm = get_llm("recipe", temperature=0.2, retry_owner="application")
        _structured_llm = _llm.with_structured_output(RecipeOutput)
    return _structured_llm


def _extract_user_input(state: ShoppingState) -> str:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content", "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                return getattr(msg, "content", "")
    return ""


def _generate_items(dish: str, people: int) -> list[dict]:
    prompt = RECIPE_GENERATE_PROMPT.format(dish=dish, people=people)
    try:
        # Claude API는 system 메시지만 있고 user 메시지가 없으면 거부한다
        # ("messages: at least one message is required") — HumanMessage로 보낸다.
        # retry_call: TRANSIENT_TECHNICAL(연결/타임아웃/429/5xx)만 최대 3회 재시도,
        # 그 외(PERMANENT_TECHNICAL/QUALITY_VALIDATION)는 즉시 re-raise되어 아래 except로.
        result: RecipeOutput = retry_call(_get_llm().invoke, [HumanMessage(content=prompt)])
        return [item.model_dump() for item in result.items]
    except Exception as e:
        fc = classify_failure(e)
        agent_logger.log(f"[recipe_agent] 재료 생성 오류({fc.value}): {e}")
        return []


def _remove_ingredients(user_message: str, items: list[dict]) -> list[dict]:
    return [item for item in items if item["name"] not in user_message]


def _format_list_message(dish: str, people: Optional[int], items: list[dict]) -> str:
    people_str = f"{people}인 기준 " if people else ""
    lines = [f"{people_str}{dish} 재료예요:"]
    for item in items:
        lines.append(f"  {item['name']} {item['quantity']}{item['unit']}")
    lines.append("혹시 빼고 싶은 게 있으면 말씀해 주세요.")
    return "\n".join(lines)


def recipe_agent_node(state: RecipeAgentInput) -> RecipeAgentUpdate:
    stage = state.get("stage")
    recipe_dish = state.get("recipe_dish") or ""
    recipe_people = state.get("recipe_people") or 4
    queue_items = list(state.get("queue_items") or [])
    user_message = _extract_user_input(state)

    agent_logger.log(
        f"[recipe_agent] 진입 | stage={stage} dish={recipe_dish} "
        f"items={len(queue_items)}"
    )

    # Mode 3(재료 확정→쇼핑 시작)/Mode 4(담기 후 다음 재료 안내)는
    # purchase_queue_agent로 완전히 이동했다(Unit 2) — route()/after_payment_agent가
    # 이제 그 경우엔 recipe_agent를 아예 거치지 않고 purchase_queue_agent로 직접
    # 보낸다. 여기 남는 건 Mode 1(재료 추론)/Mode 2(재료 편집)뿐이다.

    # ── Mode 2: 재료 제거 편집 ──
    if stage == "recipe_planning" and queue_items:
        updated = _remove_ingredients(user_message, queue_items)
        msg = _format_list_message(recipe_dish, recipe_people, updated if updated != queue_items else queue_items)
        output = {
            "queue_items": updated,
            "stage": "recipe_planning",
            "pending_action": {"type": "ingredient_confirm", "message": msg},
            "last_agent": "recipe_agent",
            "error": None,
        }
        agent_logger.log(f"[recipe_agent] Mode 2 | {len(queue_items)}→{len(updated)}개")
        return output

    # ── Mode 1: 재료 목록 생성 ──
    if not recipe_dish:
        return {
            "stage": "idle",
            "needs_clarification": True,
            "clarification_reason": "어떤 요리의 재료를 찾으시나요?",
            "last_agent": "recipe_agent",
            "error": "missing_recipe_dish",
        }

    items = _generate_items(recipe_dish, recipe_people)
    if not items:
        return {
            "stage": "idle",
            "error": "recipe_generation_failed",
            "last_agent": "recipe_agent",
            "degraded_mode": True,
            "failure_stage": "recipe_llm",
        }

    msg = _format_list_message(recipe_dish, recipe_people, items)
    output = {
        # purchase_queue_agent(Mode 3/4)가 실제로 읽는 필드. queue_source="recipe"로
        # 이 큐의 출처를 명시해서, purchase_queue_agent가 recipe_dish를 직접
        # 참조하지 않아도 되게 한다(recipe_dish 개념을 모르는 범용 실행기로 유지).
        "queue_items": items,
        "current_queue_index": 0,
        "queue_source": "recipe",
        "stage": "recipe_planning",
        "pending_action": {"type": "ingredient_confirm", "message": msg},
        "last_agent": "recipe_agent",
        "error": None,
    }
    agent_logger.log(f"[recipe_agent] Mode 1 | {recipe_dish} 재료 {len(items)}개 생성")
    return output

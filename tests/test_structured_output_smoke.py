"""
구조화출력 스모크 테스트 — 실 LLM으로 각 에이전트의 Pydantic 스키마가
실제로 통과하는지만 확인한다 (품질 평가 아님, evals/ 쪽 담당).

배경: intent_agent가 method="json_schema"를 쓰다가 스키마가 너무 복잡해서
("Schema is too complex" / "Grammar compilation timed out") 5일간 조용히
전부 실패하고 있었는데, 그동안 아무도 실LLM으로 안 불러봐서 못 잡았다.
이 테스트는 그 재발을 막기 위한 최소 안전망이다.

새 에이전트를 추가하거나 기존 Pydantic 스키마(특히 method="json_schema"
쓰는 곳)를 고치면, 이 파일에 케이스를 추가하고 한 번은 꼭 돌려볼 것.

실행: pytest -m llm_smoke -v  (기본 pytest 실행에는 안 걸림 — 실 API 호출이라
     비용/시간이 들기 때문. 새 스키마 추가 시 수동으로 돌려서 확인.)
"""
import os

import pytest
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()
os.environ.setdefault("DB_MODE", "mock")
os.environ["LANGCHAIN_TRACING_V2"] = "false"

pytestmark = pytest.mark.llm_smoke


def test_intent_agent_schema():
    from src.agents.intent_agent import IntentOutput, _get_llm

    result = _get_llm().invoke([HumanMessage(content="우유 사줘")])
    assert isinstance(result, IntentOutput)


def test_context_agent_safety_sync_schema():
    from src.agents.context_agent import SafetySignalUpdate, _get_llm
    from src.prompts.context_prompt import SAFETY_SYNC_PROMPT

    prompt = SAFETY_SYNC_PROMPT.format(session_text="저 우유 알레르기 있어요")
    result = _get_llm().with_structured_output(SafetySignalUpdate, method="json_schema").invoke(
        [HumanMessage(content=prompt)]
    )
    assert isinstance(result, SafetySignalUpdate)


def test_context_agent_classification_schema():
    from src.agents.context_agent import ContextAgentOutput, _get_llm
    from src.prompts.context_prompt import CONTEXT_CLASSIFICATION_PROMPT

    prompt = CONTEXT_CLASSIFICATION_PROMPT.format(
        profile_summary="없음",
        general_preference_summary="없음",
        keyword_history_lines="없음",
        session_text="우유 사려는데 저당인 걸로 주세요",
        current_keywords="우유",
    )
    result = _get_llm().with_structured_output(ContextAgentOutput, method="json_schema").invoke(
        [HumanMessage(content=prompt)]
    )
    assert isinstance(result, ContextAgentOutput)


def test_product_agent_scoring_schema():
    from src.agents.product_agent import ScoringLLMOutput, _get_llm
    from src.prompts.scoring_prompt import SCORING_PROMPT

    candidates = "[A] 서울우유 1L  2,500원  (naver)\n[B] 매일우유 1L  2,700원  (kurly)"
    prompt = SCORING_PROMPT.format(
        keywords='["우유"]',
        condition="없음",
        soft_preferences="없음",
        formatted_candidates=candidates,
    )
    result = _get_llm().with_structured_output(ScoringLLMOutput, method="json_schema").invoke(
        [HumanMessage(content=prompt)]
    )
    assert isinstance(result, ScoringLLMOutput)


def test_recipe_agent_schema():
    from src.agents.recipe_agent import RecipeOutput, _get_llm
    from src.prompts.recipe_prompt import RECIPE_GENERATE_PROMPT

    prompt = RECIPE_GENERATE_PROMPT.format(dish="된장찌개", people=2)
    result = _get_llm().invoke([HumanMessage(content=prompt)])
    assert isinstance(result, RecipeOutput)


def test_smalltalk_agent_schema():
    from src.agents.smalltalk_agent import SmalltalkOutput, _get_llm
    from src.prompts.smalltalk_prompt import SMALLTALK_GREETING_PROMPT

    prompt = SMALLTALK_GREETING_PROMPT.format(user_input="안녕하세요")
    result = _get_llm().with_structured_output(SmalltalkOutput, method="json_schema").invoke(
        [HumanMessage(content=prompt)]
    )
    assert isinstance(result, SmalltalkOutput)

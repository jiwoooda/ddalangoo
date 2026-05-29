"""
Product Agent 평가 실행 스크립트.
Dataset 'product-agent-eval'의 예제마다 실제 Product Agent를 호출하고
1순위 상품 정확도 + 설명 품질(LLM 채점)을 LangSmith에 기록한다.

실행:
    cd backend
    python evaluations/run_product_eval.py
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../vendor/ddalangoo-langgraph"))
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from langsmith import evaluate
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from src.agents.product_agent import product_agent_node


# ── 평가 대상 함수 ──────────────────────────────────────────────────
def target(inputs: dict) -> dict:
    """Dataset 입력으로 Product Agent를 실행하고 결과를 반환한다."""
    messages = []
    if inputs.get("user_question"):
        messages = [HumanMessage(content=inputs["user_question"])]

    state = {
        "messages": messages,
        "search_results": inputs.get("search_results", []),
        "recommended_products": [],
        "selected_product": None,
        "current_product_index": inputs.get("current_product_index", 0),
        "condition": inputs.get("condition"),
        "quantity": None,
        "keywords": inputs.get("keywords", []),
        "intent": inputs.get("intent", "buy"),
        "pending_action": None,
        "recommendation_context": {},
    }
    result = product_agent_node(state)
    selected = result.get("selected_product") or {}
    return {
        "rank1_product": selected.get("product_name") or selected.get("name"),
        "explanation": result.get("explanation", ""),
    }


# ── Evaluator 함수들 ────────────────────────────────────────────────
def eval_rank1_match(run, example):
    """1순위 추천 상품이 정답과 일치하는가."""
    predicted = (run.outputs or {}).get("rank1_product", "")
    expected = (example.outputs or {}).get("expected_rank1_product", "")
    score = 1.0 if predicted == expected else 0.0
    return {"key": "rank1_match", "score": score}


def eval_explanation_quality(run, example):
    """LLM이 explanation의 품질을 0~1로 채점한다."""
    explanation = (run.outputs or {}).get("explanation", "")
    condition = example.inputs.get("condition") or "없음"
    keywords = example.inputs.get("keywords", [])

    if not explanation:
        return {"key": "explanation_quality", "score": 0.0}

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    prompt = f"""쇼핑 어시스턴트의 상품 추천 설명 품질을 평가해주세요.

검색 조건: {condition}
검색 키워드: {keywords}
추천 설명: {explanation}

평가 기준:
1. 조건(condition)에 맞는 이유가 포함되어 있는가?
2. 키워드와 관련된 상품을 언급하는가?
3. 사용자가 이해하기 쉬운가?

숫자 하나만 반환하세요 (0.0~1.0). 예시: 0.8"""

    try:
        response = llm.invoke(prompt)
        score = float(response.content.strip())
        score = max(0.0, min(1.0, score))
    except Exception:
        score = 0.5
    return {"key": "explanation_quality", "score": round(score, 4)}


# ── 실행 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Product Agent 평가 시작 ===")
    results = evaluate(
        target,
        data="product-agent-eval",
        evaluators=[eval_rank1_match, eval_explanation_quality],
        experiment_prefix="product-agent",
        metadata={"model": "claude-sonnet-4-6", "version": "v1"},
    )
    print("\n=== 평가 완료 ===")
    print("결과 확인: https://smith.langchain.com → 프로젝트 ddalangoo → Experiments 탭")

"""
Intent Agent 평가 실행 스크립트.
Dataset 'intent-agent-eval'의 예제마다 실제 Intent Agent를 호출하고
intent / keyword / condition / quantity 정확도를 LangSmith에 기록한다.

실행:
    cd backend
    python evaluations/run_intent_eval.py
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
from src.agents.intent_agent import intent_agent_node


# ── 평가 대상 함수 ──────────────────────────────────────────────────
def target(inputs: dict) -> dict:
    """Dataset 입력으로 Intent Agent를 실행하고 결과를 반환한다."""
    pending = inputs.get("pending_action")
    state = {
        "messages": [HumanMessage(content=inputs["user_input"])],
        "stage": inputs.get("stage", "idle"),
        "pending_action": {"type": pending} if pending else None,
        "keywords": [],
        "quantity": None,
    }
    result = intent_agent_node(state)
    return {
        "intent": result.get("intent"),
        "keywords": result.get("keywords", []),
        "condition": result.get("condition"),
        "quantity": result.get("quantity"),
        "needs_clarification": result.get("needs_clarification", False),
    }


# ── Evaluator 함수들 ────────────────────────────────────────────────
def eval_intent_match(run, example):
    """정답 intent와 정확히 일치하는가."""
    predicted = (run.outputs or {}).get("intent")
    expected = (example.outputs or {}).get("intent")
    return {"key": "intent_match", "score": 1.0 if predicted == expected else 0.0}


def eval_keyword_f1(run, example):
    """
    검색 쿼리 기준 토큰 F1.
    키워드 리스트를 공백으로 합쳐 실제 검색 쿼리로 비교하므로
    ["강아지", "간식"] vs ["강아지 간식"] → 동일 토큰 집합 → 1.0
    """
    predicted_list = (run.outputs or {}).get("keywords", [])
    expected_list = (example.outputs or {}).get("keywords", [])

    predicted_tokens = set(" ".join(predicted_list).lower().split())
    expected_tokens = set(" ".join(expected_list).lower().split())

    if not expected_tokens and not predicted_tokens:
        return {"key": "keyword_f1", "score": 1.0}
    if not expected_tokens:
        return {"key": "keyword_f1", "score": 1.0 if not predicted_tokens else 0.5}
    if not predicted_tokens:
        return {"key": "keyword_f1", "score": 0.0, "comment": f"expected={sorted(expected_tokens)}, got=[]"}

    overlap = predicted_tokens & expected_tokens
    precision = len(overlap) / len(predicted_tokens)
    recall = len(overlap) / len(expected_tokens)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "key": "keyword_f1",
        "score": round(f1, 4),
        "comment": f"expected={sorted(expected_tokens)}, got={sorted(predicted_tokens)}",
    }


def eval_condition_match(run, example):
    """정답 condition과 정확히 일치하는가."""
    predicted = (run.outputs or {}).get("condition")
    expected = (example.outputs or {}).get("condition")
    return {"key": "condition_match", "score": 1.0 if predicted == expected else 0.0}


def eval_quantity_match(run, example):
    """정답 quantity와 정확히 일치하는가."""
    predicted = (run.outputs or {}).get("quantity")
    expected = (example.outputs or {}).get("quantity")
    return {"key": "quantity_match", "score": 1.0 if predicted == expected else 0.0}


def eval_clarification_match(run, example):
    """needs_clarification 예측이 정답과 일치하는가."""
    predicted = (run.outputs or {}).get("needs_clarification", False)
    expected = (example.outputs or {}).get("needs_clarification", False)
    return {"key": "clarification_match", "score": 1.0 if predicted == expected else 0.0}


# ── 실행 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Intent Agent 평가 시작 ===")
    results = evaluate(
        target,
        data="intent-agent-eval",
        evaluators=[
            eval_intent_match,
            eval_keyword_f1,
            eval_condition_match,
            eval_quantity_match,
            eval_clarification_match,
        ],
        experiment_prefix="intent-agent",
        metadata={"model": "gpt-4o-mini", "version": "v1"},
    )
    print("\n=== 평가 완료 ===")
    print("결과 확인: https://smith.langchain.com → 프로젝트 ddalangoo → Experiments 탭")

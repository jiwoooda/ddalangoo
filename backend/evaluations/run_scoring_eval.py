"""
Recommendation Scoring 평가 실행 스크립트.
Dataset 'recommendation-scoring-eval'의 예제마다 실제 룰 기반 스코어링을 실행하고
1순위 정확도를 LangSmith에 기록한다.

실행:
    cd backend
    python evaluations/run_scoring_eval.py
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

from langsmith import evaluate
from app.services.recommendation_scoring_service import rank_candidates_rule_based


# ── 평가 대상 함수 ──────────────────────────────────────────────────
def target(inputs: dict) -> dict:
    """Dataset 입력으로 룰 기반 스코어링을 실행하고 결과를 반환한다."""
    ranked = rank_candidates_rule_based(
        inputs["candidates"],
        keywords=inputs.get("keywords", []),
        intent=inputs.get("intent", "buy"),
        condition=inputs.get("condition"),
        purchase_histories=inputs.get("purchase_histories"),
    )
    return {
        "rank1_product": ranked[0]["product_name"] if ranked else None,
        "ranked_products": [r["product_name"] for r in ranked],
        "rank1_score": ranked[0].get("score") if ranked else None,
        "rank1_score_detail": ranked[0].get("score_detail") if ranked else None,
    }


# ── Evaluator 함수들 ────────────────────────────────────────────────
def eval_rank1_match(run, example):
    """1순위 상품이 정답과 일치하는가."""
    predicted = (run.outputs or {}).get("rank1_product", "")
    expected = (example.outputs or {}).get("expected_rank1", "")
    return {"key": "rank1_match", "score": 1.0 if predicted == expected else 0.0}


def eval_score_above_threshold(run, example):
    """1순위 상품의 점수가 0.5 이상인가 (품질 기준)."""
    score = (run.outputs or {}).get("rank1_score") or 0.0
    return {"key": "score_above_threshold", "score": 1.0 if score >= 0.5 else 0.0}


# ── 실행 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Recommendation Scoring 평가 시작 ===")
    results = evaluate(
        target,
        data="recommendation-scoring-eval",
        evaluators=[eval_rank1_match, eval_score_above_threshold],
        experiment_prefix="recommendation-scoring",
        metadata={"mode": "rule_based_v1", "version": "v1"},
    )
    print("\n=== 평가 완료 ===")
    print("결과 확인: https://smith.langchain.com → 프로젝트 ddalangoo → Experiments 탭")

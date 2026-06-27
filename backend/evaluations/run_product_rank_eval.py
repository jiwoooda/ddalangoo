"""
Product Rank 평가 스크립트.

핵심 검증:
  1. filtered_out 정밀도(precision): 실제로 관련 없는 상품만 제외하는가
  2. filtered_out 재현율(recall):    관련 없는 상품을 빠짐없이 제외하는가
  3. condition 1순위 정확도:         최저가/리뷰좋은 등 조건에 맞는 상품이 1위인가

실행:
    cd backend
    python evaluations/run_product_rank_eval.py
"""
import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../vendor/ddalangoo-langgraph"))
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import os
os.environ['LANGCHAIN_ENDPOINT'] = 'https://apac.api.smith.langchain.com'

from langsmith import Client, evaluate
from langchain_core.messages import HumanMessage
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool as lc_tool
from src.prompts.product_prompt import PRODUCT_RANK_PROMPT

DATASET_NAME = "product-rank-eval"

# ── 데이터셋 예제 ──────────────────────────────────────────────────
EXAMPLES = [
    {
        "inputs": {
            "keywords": ["두부"],
            "condition": None,
            "preference_context": "선호 정보 없음",
            "candidates": [
                {"label": "A", "product_name": "풀무원 두부 300g", "price": 2200, "rating": 4.5, "review_count": 1200},
                {"label": "B", "product_name": "CJ 두부면 200g", "price": 3500, "rating": 4.2, "review_count": 800},
                {"label": "C", "product_name": "매일유업 순두부 200g", "price": 1800, "rating": 4.3, "review_count": 950},
                {"label": "D", "product_name": "유부초밥 키트 300g", "price": 4200, "rating": 4.0, "review_count": 500},
                {"label": "E", "product_name": "풀무원 연두부 280g", "price": 2100, "rating": 4.4, "review_count": 1100},
            ],
        },
        "outputs": {
            # 두부면·유부초밥은 제외. 순두부·연두부는 두부 카테고리이므로 유지.
            "should_filter": ["B", "D"],
            "should_keep": ["A", "C", "E"],
        },
    },
    {
        "inputs": {
            "keywords": ["계란"],
            "condition": "최저가",
            "preference_context": "선호 정보 없음",
            "candidates": [
                {"label": "A", "product_name": "풀무원 달걀 10구", "price": 4900, "rating": 4.6, "review_count": 3200},
                {"label": "B", "product_name": "하림 계란 30구", "price": 9500, "rating": 4.5, "review_count": 1800},
                {"label": "C", "product_name": "계란말이 간편식 200g", "price": 5200, "rating": 4.1, "review_count": 600},
                {"label": "D", "product_name": "계란 과자 80g", "price": 1500, "rating": 3.8, "review_count": 200},
                {"label": "E", "product_name": "목초 방목란 15구", "price": 6200, "rating": 4.7, "review_count": 900},
            ],
        },
        "outputs": {
            # 계란말이 간편식·계란과자는 제외. 나머지는 유지.
            "should_filter": ["C", "D"],
            "should_keep": ["A", "B", "E"],
            # 최저가 조건: A(4900원/10구)가 단가 기준 1위
            "expected_top1_label": "A",
        },
    },
    {
        "inputs": {
            "keywords": ["사과"],
            "condition": None,
            "preference_context": "선호 정보 없음",
            "candidates": [
                {"label": "A", "product_name": "경북 사과 1kg", "price": 8900, "rating": 4.7, "review_count": 2100},
                {"label": "B", "product_name": "사과맛 젤리 150g", "price": 1200, "rating": 4.0, "review_count": 300},
                {"label": "C", "product_name": "청송 사과 3kg", "price": 18000, "rating": 4.8, "review_count": 1500},
                {"label": "D", "product_name": "사과식초 500ml", "price": 3500, "rating": 4.2, "review_count": 800},
                {"label": "E", "product_name": "홍로 사과 2kg", "price": 14000, "rating": 4.6, "review_count": 1200},
            ],
        },
        "outputs": {
            # 사과맛 젤리·사과식초는 제외
            "should_filter": ["B", "D"],
            "should_keep": ["A", "C", "E"],
        },
    },
    {
        "inputs": {
            "keywords": ["닭가슴살"],
            "condition": "리뷰좋은",
            "preference_context": "선호 정보 없음",
            "candidates": [
                {"label": "A", "product_name": "하림 닭가슴살 100g", "price": 1500, "rating": 4.3, "review_count": 800},
                {"label": "B", "product_name": "CJ 닭가슴살 소시지 200g", "price": 3200, "rating": 4.5, "review_count": 2500},
                {"label": "C", "product_name": "통 닭가슴살 500g", "price": 6800, "rating": 4.6, "review_count": 3100},
                {"label": "D", "product_name": "닭가슴살 샐러드 키트 300g", "price": 7500, "rating": 4.4, "review_count": 1200},
            ],
        },
        "outputs": {
            # 닭가슴살 소시지·샐러드 키트는 변형 상품 — 사용자가 명시하지 않았으므로 제외
            "should_filter": ["B", "D"],
            "should_keep": ["A", "C"],
            # 리뷰좋은 조건: C(리뷰 3100개)가 1위
            "expected_top1_label": "C",
        },
    },
    {
        "inputs": {
            "keywords": ["라면"],
            "condition": "최저가",
            "preference_context": "선호 브랜드: 농심. 평균 구매가: 3,500원.",
            "candidates": [
                {"label": "A", "product_name": "농심 신라면 5개입", "price": 3200, "rating": 4.8, "review_count": 9900},
                {"label": "B", "product_name": "오뚜기 진라면 5개입", "price": 2900, "rating": 4.6, "review_count": 6500},
                {"label": "C", "product_name": "삼양 불닭볶음면 5개입", "price": 4100, "rating": 4.7, "review_count": 8100},
                {"label": "D", "product_name": "라면 그릇 세트", "price": 9900, "rating": 4.2, "review_count": 300},
            ],
        },
        "outputs": {
            # 라면 그릇은 제외
            "should_filter": ["D"],
            "should_keep": ["A", "B", "C"],
            # 최저가 조건: B(2900원)가 1위 (선호 브랜드 농심보다 condition 우선)
            "expected_top1_label": "B",
        },
    },
]


# ── 데이터셋 생성 ──────────────────────────────────────────────────
def create_dataset(client: Client) -> str:
    existing = [d for d in client.list_datasets() if d.name == DATASET_NAME]
    if existing:
        print(f"기존 데이터셋 사용: {DATASET_NAME}")
        return existing[0].id

    dataset = client.create_dataset(DATASET_NAME, description="product-rank 필터링 및 condition 정렬 평가")
    for ex in EXAMPLES:
        client.create_example(inputs=ex["inputs"], outputs=ex["outputs"], dataset_id=dataset.id)
    print(f"데이터셋 생성 완료: {DATASET_NAME} ({len(EXAMPLES)}개)")
    return dataset.id


# ── 평가 대상 함수 ──────────────────────────────────────────────────
def _make_rank_tool(candidates):
    label_map = {c["label"]: c for c in candidates}
    result_holder = {}

    @lc_tool
    def rank_products(ranked_labels: list[str], filtered_out_labels: list[str] = []) -> str:
        """후보 상품을 순위대로 정렬. ranked_labels: 1위부터 레이블 리스트."""
        result_holder["ranked"] = [l.upper() for l in ranked_labels]
        result_holder["filtered"] = [l.upper() for l in filtered_out_labels]
        return json.dumps({"ranked": ranked_labels, "filtered": filtered_out_labels})

    return rank_products, result_holder


def _format_products(candidates):
    lines = []
    for c in candidates:
        label = c["label"]
        name = c["product_name"]
        price = c.get("price", 0)
        rating = c.get("rating")
        review = c.get("review_count")
        parts = [f"[{label}] {name}", f"{price:,}원"]
        if rating:
            parts.append(f"⭐{rating}")
        if review:
            parts.append(f"리뷰 {review:,}개")
        lines.append("  ".join(parts))
    return "\n".join(lines)


def target(inputs: dict) -> dict:
    candidates = inputs["candidates"]
    rank_tool, result_holder = _make_rank_tool(candidates)

    llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0, max_tokens=800)
    prompt = PRODUCT_RANK_PROMPT.format(
        keywords=json.dumps(inputs["keywords"], ensure_ascii=False),
        condition=inputs["condition"] or "없음",
        preference_context=inputs["preference_context"],
        formatted_products=_format_products(candidates),
    )
    response = llm.bind_tools([rank_tool]).invoke([HumanMessage(content=prompt)])
    if response.tool_calls:
        rank_tool.invoke(response.tool_calls[0]["args"])

    return {
        "ranked_labels": result_holder.get("ranked", []),
        "filtered_labels": result_holder.get("filtered", []),
        "top1_label": result_holder.get("ranked", [""])[0] if result_holder.get("ranked") else "",
    }


# ── Evaluator 함수들 ────────────────────────────────────────────────
def eval_filter_precision(run, example):
    """filtered_out에 잘못 포함된 상품 없는지 (should_keep인데 필터됨)."""
    filtered = set(f.upper() for f in (run.outputs or {}).get("filtered_labels", []))
    should_keep = set(s.upper() for s in (example.outputs or {}).get("should_keep", []))
    false_positives = filtered & should_keep
    score = 1.0 if not false_positives else 1.0 - len(false_positives) / max(len(should_keep), 1)
    return {"key": "filter_precision", "score": round(score, 4)}


def eval_filter_recall(run, example):
    """관련 없는 상품이 빠짐없이 filtered_out에 포함됐는지."""
    filtered = set(f.upper() for f in (run.outputs or {}).get("filtered_labels", []))
    should_filter = set(s.upper() for s in (example.outputs or {}).get("should_filter", []))
    if not should_filter:
        return {"key": "filter_recall", "score": 1.0}
    caught = filtered & should_filter
    score = len(caught) / len(should_filter)
    return {"key": "filter_recall", "score": round(score, 4)}


def eval_top1_condition_match(run, example):
    """condition 있는 케이스에서 1위 상품이 정답인지."""
    expected = (example.outputs or {}).get("expected_top1_label")
    if not expected:
        return {"key": "top1_condition_match", "score": 1.0}  # 해당 없는 케이스
    predicted = ((run.outputs or {}).get("top1_label") or "").upper()
    return {"key": "top1_condition_match", "score": 1.0 if predicted == expected.upper() else 0.0}


# ── 실행 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    client = Client(
        api_url="https://apac.api.smith.langchain.com",
        api_key=os.environ.get("LANGCHAIN_API_KEY"),
    )
    create_dataset(client)

    print("=== Product Rank 평가 시작 ===")
    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[eval_filter_precision, eval_filter_recall, eval_top1_condition_match],
        experiment_prefix="product-rank",
        metadata={"model": "claude-sonnet-4-6", "version": "v1"},
    )
    print("\n=== 평가 완료 ===")

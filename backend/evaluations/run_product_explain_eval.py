"""
Product Explain 평가 스크립트.

핵심 검증:
  1. 문장 수: 정확히 2문장인가
  2. 1문장 구조: 상품명 + 가격 포함인가
  3. 2문장 구조: "주문할까요?" 포함인가
  4. condition별 추천 이유: 최저가→"가장 저렴", 리뷰좋은→"리뷰가 가장 많은"

실행:
    cd backend
    python evaluations/run_product_explain_eval.py
"""
import sys, os, json, re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../vendor/ddalangoo-langgraph"))
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

os.environ['LANGCHAIN_ENDPOINT'] = 'https://apac.api.smith.langchain.com'

from langsmith import Client, evaluate
from langchain_core.messages import HumanMessage
from langchain_anthropic import ChatAnthropic
from src.prompts.product_prompt import PRODUCT_EXPLAIN_PROMPT

DATASET_NAME = "product-explain-eval"

# ── 데이터셋 예제 ──────────────────────────────────────────────────
EXAMPLES = [
    # 1. 최저가 condition
    {
        "inputs": {
            "product": {
                "product_name": "오뚜기 진라면 5개입",
                "price": 2900,
                "rating": 4.6,
                "review_count": 6500,
                "platform": "kurly",
            },
            "keywords": ["라면"],
            "condition": "최저가",
            "preference_context": "선호 정보 없음",
        },
        "outputs": {
            "must_contain_price": "2,900",
            "must_contain_name": "진라면",
            "must_end_with": "주문할까요?",
            "condition_phrase": "저렴",  # "가장 저렴해요" 포함 기대
            "expected_sentence_count": 2,
        },
    },

    # 2. 리뷰좋은 condition
    {
        "inputs": {
            "product": {
                "product_name": "통 닭가슴살 500g",
                "price": 6800,
                "rating": 4.6,
                "review_count": 3100,
                "platform": "kurly",
            },
            "keywords": ["닭가슴살"],
            "condition": "리뷰좋은",
            "preference_context": "선호 정보 없음",
        },
        "outputs": {
            "must_contain_price": "6,800",
            "must_contain_name": "닭가슴살",
            "must_end_with": "주문할까요?",
            "condition_phrase": "리뷰",
            "expected_sentence_count": 2,
        },
    },

    # 3. condition 없음 + 브랜드 선호
    {
        "inputs": {
            "product": {
                "product_name": "농심 신라면 5개입",
                "price": 3200,
                "rating": 4.8,
                "review_count": 9900,
                "platform": "kurly",
            },
            "keywords": ["라면"],
            "condition": None,
            "preference_context": "선호 브랜드: 농심. 평균 구매가: 3,500원.",
        },
        "outputs": {
            "must_contain_price": "3,200",
            "must_contain_name": "신라면",
            "must_end_with": "주문할까요?",
            "condition_phrase": None,
            "expected_sentence_count": 2,
        },
    },

    # 4. condition 없음 + 선호 정보 없음
    {
        "inputs": {
            "product": {
                "product_name": "경북 사과 1kg",
                "price": 8900,
                "rating": 4.7,
                "review_count": 2100,
                "platform": "kurly",
            },
            "keywords": ["사과"],
            "condition": None,
            "preference_context": "선호 정보 없음",
        },
        "outputs": {
            "must_contain_price": "8,900",
            "must_contain_name": "사과",
            "must_end_with": "주문할까요?",
            "condition_phrase": None,
            "expected_sentence_count": 2,
        },
    },

    # 5. 가성비 condition
    {
        "inputs": {
            "product": {
                "product_name": "풀무원 두부 300g",
                "price": 2200,
                "rating": 4.5,
                "review_count": 1200,
                "platform": "kurly",
            },
            "keywords": ["두부"],
            "condition": "가성비",
            "preference_context": "선호 정보 없음",
        },
        "outputs": {
            "must_contain_price": "2,200",
            "must_contain_name": "두부",
            "must_end_with": "주문할까요?",
            "condition_phrase": "합리적",  # "가격이 합리적인 상품이에요"
            "expected_sentence_count": 2,
        },
    },

    # 6. 빠른배송 condition + delivery 필드 있음
    {
        "inputs": {
            "product": {
                "product_name": "하림 닭가슴살 100g",
                "price": 1500,
                "rating": 4.3,
                "review_count": 800,
                "platform": "kurly",
                "delivery": "오늘 도착",
            },
            "keywords": ["닭가슴살"],
            "condition": "빠른배송",
            "preference_context": "선호 정보 없음",
        },
        "outputs": {
            "must_contain_price": "1,500",
            "must_contain_name": "닭가슴살",
            "must_end_with": "주문할까요?",
            "condition_phrase": None,  # 배송 언급 기대하지만 condition_phrase 검증은 완화
            "expected_sentence_count": 2,
        },
    },
]


# ── 데이터셋 생성 ──────────────────────────────────────────────────
def create_dataset(client: Client) -> str:
    existing = [d for d in client.list_datasets() if d.name == DATASET_NAME]
    if existing:
        print(f"기존 데이터셋 사용: {DATASET_NAME}")
        return existing[0].id

    dataset = client.create_dataset(DATASET_NAME, description="product-explain TTS 2문장 구조 및 condition별 추천 이유 평가")
    for ex in EXAMPLES:
        client.create_example(inputs=ex["inputs"], outputs=ex["outputs"], dataset_id=dataset.id)
    print(f"데이터셋 생성 완료: {DATASET_NAME} ({len(EXAMPLES)}개)")
    return dataset.id


# ── 평가 대상 함수 ──────────────────────────────────────────────────
def target(inputs: dict) -> dict:
    llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0, max_tokens=400)
    product = inputs["product"]
    prompt = PRODUCT_EXPLAIN_PROMPT.format(
        product_json=json.dumps(product, ensure_ascii=False),
        keywords=json.dumps(inputs["keywords"], ensure_ascii=False),
        condition=inputs["condition"] or "없음",
        preference_context=inputs["preference_context"],
    )
    explanation = llm.invoke([HumanMessage(content=prompt)]).content.strip()
    sentences = [s.strip() for s in re.split(r'(?<=[.?!。])\s+', explanation) if s.strip()]
    return {
        "explanation": explanation,
        "sentence_count": len(sentences),
        "first_sentence": sentences[0] if sentences else "",
        "last_sentence": sentences[-1] if sentences else "",
    }


# ── Evaluators ──────────────────────────────────────────────────────
def eval_sentence_count(run, example):
    expected = (example.outputs or {}).get("expected_sentence_count", 2)
    predicted = (run.outputs or {}).get("sentence_count", 0)
    return {
        "key": "sentence_count",
        "score": 1.0 if predicted == expected else 0.0,
        "comment": f"expected={expected}문장, got={predicted}문장",
    }


def eval_contains_price(run, example):
    expected_price = (example.outputs or {}).get("must_contain_price", "")
    if not expected_price:
        return {"key": "contains_price", "score": 1.0}
    explanation = (run.outputs or {}).get("explanation", "")
    return {
        "key": "contains_price",
        "score": 1.0 if expected_price in explanation else 0.0,
        "comment": f"찾는 가격: {expected_price}",
    }


def eval_contains_name(run, example):
    expected_name = (example.outputs or {}).get("must_contain_name", "")
    if not expected_name:
        return {"key": "contains_name", "score": 1.0}
    explanation = (run.outputs or {}).get("explanation", "")
    return {
        "key": "contains_name",
        "score": 1.0 if expected_name in explanation else 0.0,
        "comment": f"찾는 이름: {expected_name}",
    }


def eval_ends_with_question(run, example):
    suffix = (example.outputs or {}).get("must_end_with", "")
    if not suffix:
        return {"key": "ends_with_question", "score": 1.0}
    explanation = (run.outputs or {}).get("explanation", "")
    return {
        "key": "ends_with_question",
        "score": 1.0 if explanation.endswith(suffix) else 0.0,
        "comment": f"suffix='{suffix}', actual_end='{explanation[-20:]}'",
    }


def eval_condition_phrase(run, example):
    condition_phrase = (example.outputs or {}).get("condition_phrase")
    if not condition_phrase:
        return {"key": "condition_phrase", "score": 1.0}
    explanation = (run.outputs or {}).get("explanation", "")
    return {
        "key": "condition_phrase",
        "score": 1.0 if condition_phrase in explanation else 0.0,
        "comment": f"기대 키워드: {condition_phrase}",
    }


# ── 실행 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    client = Client(
        api_url="https://apac.api.smith.langchain.com",
        api_key=os.environ.get("LANGCHAIN_API_KEY"),
    )
    create_dataset(client)

    print("=== Product Explain 평가 시작 ===")
    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[
            eval_sentence_count,
            eval_contains_price,
            eval_contains_name,
            eval_ends_with_question,
            eval_condition_phrase,
        ],
        experiment_prefix="product-explain",
        metadata={"model": "claude-sonnet-4-6", "version": "v1"},
    )
    print("\n=== 평가 완료 ===")

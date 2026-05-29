"""
LangSmith 평가용 Dataset 일괄 생성 스크립트.
한 번만 실행하면 3개의 Dataset이 LangSmith에 생성된다.

  - intent-agent-eval        : Intent Agent 평가
  - product-agent-eval       : Product Agent 평가
  - recommendation-scoring-eval : 추천 스코어링 평가
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from langsmith import Client

LANGSMITH_UI = "https://smith.langchain.com"

# ──────────────────────────────────────────────────────────────────
# 1. Intent Agent Dataset
# ──────────────────────────────────────────────────────────────────
INTENT_DATASET_NAME = "intent-agent-eval"
INTENT_EXAMPLES = [
    # 명확한 구매 (5개)
    {
        "input": {"user_input": "사과 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["사과"], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "두부 두 개 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["두부"], "condition": None, "quantity": 2, "needs_clarification": False},
    },
    {
        "input": {"user_input": "강아지 간식 주문해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["강아지 간식"], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "세탁세제 사고 싶어", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["세탁세제"], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "우유 세 개 주문해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["우유"], "condition": None, "quantity": 3, "needs_clarification": False},
    },
    # 조건 포함 구매 (4개)
    {
        "input": {"user_input": "사과 싸게 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["사과"], "condition": "최저가", "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "두부 빠른배송으로 주문해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["두부"], "condition": "빠른배송", "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "리뷰 좋은 샴푸 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["샴푸"], "condition": "리뷰좋은", "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "가성비 좋은 노트북 가방 보여줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["노트북 가방"], "condition": "가성비", "quantity": None, "needs_clarification": False},
    },
    # 재구매 (2개)
    {
        "input": {"user_input": "저번에 산 두부 또 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "reorder", "keywords": ["두부"], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "지난번에 주문한 거 다시 주문해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "reorder", "keywords": [], "condition": None, "quantity": None, "needs_clarification": False},
    },
    # 확인 / 거절 (3개)
    {
        "input": {"user_input": "응 그걸로 할게", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "confirm", "keywords": [], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "아니 다른 거 보여줘", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "deny", "keywords": [], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "3개로 할게", "stage": "product_confirming", "pending_action": "quantity_confirm"},
        "output": {"intent": "confirm", "keywords": [], "condition": None, "quantity": 3, "needs_clarification": False},
    },
    # 다음 상품 / 플랫폼 비교 / 취소 (3개)
    {
        "input": {"user_input": "다른 거 보여줘", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "next", "keywords": [], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "쿠팡이랑 네이버 둘 다 비교해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "compare_platforms", "keywords": [], "condition": None, "quantity": None, "needs_clarification": False},
    },
    {
        "input": {"user_input": "취소할게", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "cancel", "keywords": [], "condition": None, "quantity": None, "needs_clarification": False},
    },
    # 모호 / 불명확 (3개)
    {
        "input": {"user_input": "음...", "stage": "idle", "pending_action": None},
        "output": {"intent": "unclear", "keywords": [], "condition": None, "quantity": None, "needs_clarification": True},
    },
    {
        "input": {"user_input": "그냥 뭔가 맛있는 거", "stage": "idle", "pending_action": None},
        "output": {"intent": "unclear", "keywords": [], "condition": None, "quantity": None, "needs_clarification": True},
    },
    {
        "input": {"user_input": "아 몰라", "stage": "idle", "pending_action": None},
        "output": {"intent": "unclear", "keywords": [], "condition": None, "quantity": None, "needs_clarification": True},
    },
]

# ──────────────────────────────────────────────────────────────────
# 2. Product Agent Dataset
# ──────────────────────────────────────────────────────────────────
PRODUCT_DATASET_NAME = "product-agent-eval"
PRODUCT_EXAMPLES = [
    # 최저가 조건 → 가장 저렴한 상품이 선택되어야 함
    {
        "input": {
            "keywords": ["사과"],
            "condition": "최저가",
            "intent": "buy",
            "search_results": [
                {"product_name": "부사 사과 1kg", "price": 8900, "rating": 4.2, "review_count": 320, "delivery_info": "일반배송", "platform": "coupang"},
                {"product_name": "사과 선물세트 2kg", "price": 24000, "rating": 4.8, "review_count": 1200, "delivery_info": "로켓배송", "platform": "coupang"},
                {"product_name": "국산 사과 500g", "price": 5900, "rating": 3.9, "review_count": 85, "delivery_info": "일반배송", "platform": "naver"},
            ],
        },
        "output": {
            "expected_rank1_product": "국산 사과 500g",
            "reason": "최저가 조건이므로 가격이 가장 낮은 상품이 1순위여야 한다.",
        },
    },
    # 빠른배송 조건 → 로켓/새벽 배송 상품이 선택되어야 함
    {
        "input": {
            "keywords": ["우유"],
            "condition": "빠른배송",
            "intent": "buy",
            "search_results": [
                {"product_name": "서울우유 1L", "price": 2800, "rating": 4.5, "review_count": 5000, "delivery_info": "일반배송 3-4일", "platform": "naver"},
                {"product_name": "매일우유 1L", "price": 3100, "rating": 4.6, "review_count": 3200, "delivery_info": "로켓배송 내일도착", "platform": "coupang"},
                {"product_name": "연세우유 1L", "price": 3500, "rating": 4.3, "review_count": 890, "delivery_info": "새벽배송", "platform": "kurly"},
            ],
        },
        "output": {
            "expected_rank1_product": "매일우유 1L",
            "reason": "빠른배송 조건이므로 로켓배송/새벽배송 상품이 우선이어야 한다.",
        },
    },
    # 리뷰 좋은 조건 → 평점 높고 리뷰 많은 상품이 선택되어야 함
    {
        "input": {
            "keywords": ["샴푸"],
            "condition": "리뷰좋은",
            "intent": "buy",
            "search_results": [
                {"product_name": "려 자양윤모 샴푸 400ml", "price": 12000, "rating": 4.9, "review_count": 8500, "delivery_info": "로켓배송", "platform": "coupang"},
                {"product_name": "판테닌 샴푸 500ml", "price": 8900, "rating": 4.1, "review_count": 420, "delivery_info": "일반배송", "platform": "naver"},
                {"product_name": "엘라스틴 샴푸 680ml", "price": 7500, "rating": 3.8, "review_count": 210, "delivery_info": "일반배송", "platform": "naver"},
            ],
        },
        "output": {
            "expected_rank1_product": "려 자양윤모 샴푸 400ml",
            "reason": "리뷰좋은 조건이므로 평점(4.9)과 리뷰 수(8500)가 가장 높은 상품이 1순위여야 한다.",
        },
    },
    # 다음 상품 요청 → 현재 추천 말고 다른 상품 추천
    {
        "input": {
            "keywords": ["두부"],
            "condition": None,
            "intent": "next",
            "search_results": [
                {"product_name": "풀무원 두부 300g", "price": 2200, "rating": 4.5, "review_count": 2100, "delivery_info": "로켓배송", "platform": "coupang"},
                {"product_name": "CJ 비비고 두부 400g", "price": 2500, "rating": 4.3, "review_count": 980, "delivery_info": "일반배송", "platform": "naver"},
            ],
            "current_product_index": 0,
        },
        "output": {
            "expected_rank1_product": "CJ 비비고 두부 400g",
            "reason": "next intent이므로 현재 index(0)의 다음 상품이 추천되어야 한다.",
        },
    },
    # 가성비 조건 → 가격 대비 품질 균형
    {
        "input": {
            "keywords": ["세탁세제"],
            "condition": "가성비",
            "intent": "buy",
            "search_results": [
                {"product_name": "피죤 세탁세제 3L", "price": 6900, "rating": 4.4, "review_count": 3200, "delivery_info": "로켓배송", "platform": "coupang"},
                {"product_name": "아리엘 세탁세제 5kg", "price": 35000, "rating": 4.8, "review_count": 12000, "delivery_info": "로켓배송", "platform": "coupang"},
                {"product_name": "LG 테크 세탁세제 2L", "price": 5500, "rating": 4.2, "review_count": 1500, "delivery_info": "일반배송", "platform": "naver"},
            ],
        },
        "output": {
            "expected_rank1_product": "피죤 세탁세제 3L",
            "reason": "가성비 조건이므로 가격 대비 용량/평점 균형이 좋은 상품이 1순위여야 한다.",
        },
    },
    # 상품 QA → 질문에 대한 답변 포함 여부
    {
        "input": {
            "keywords": ["에어팟"],
            "condition": None,
            "intent": "ask",
            "user_question": "배터리 얼마나 가?",
            "search_results": [
                {"product_name": "애플 에어팟 4세대", "price": 189000, "rating": 4.7, "review_count": 4500, "delivery_info": "로켓배송", "platform": "coupang"},
            ],
        },
        "output": {
            "expected_rank1_product": "애플 에어팟 4세대",
            "explanation_should_contain": "배터리",
            "reason": "ask intent이므로 explanation에 배터리 관련 답변이 포함되어야 한다.",
        },
    },
]

# ──────────────────────────────────────────────────────────────────
# 3. Recommendation Scoring Dataset
# ──────────────────────────────────────────────────────────────────
SCORING_DATASET_NAME = "recommendation-scoring-eval"
SCORING_EXAMPLES = [
    # 최저가 조건 → price_score 가중치 최고
    {
        "input": {
            "candidates": [
                {"product_name": "A상품", "price": 3000, "rating": 4.5, "review_count": 500, "delivery_info": "로켓배송"},
                {"product_name": "B상품", "price": 8000, "rating": 4.8, "review_count": 2000, "delivery_info": "로켓배송"},
                {"product_name": "C상품", "price": 5500, "rating": 4.2, "review_count": 300, "delivery_info": "일반배송"},
            ],
            "condition": "최저가",
            "keywords": ["상품"],
            "intent": "buy",
        },
        "output": {
            "expected_rank1": "A상품",
            "reason": "최저가 조건에서 price 가중치 35% → 가장 저렴한 A상품이 1위여야 한다.",
        },
    },
    # 빠른배송 조건 → delivery_score 가중치 최고
    {
        "input": {
            "candidates": [
                {"product_name": "A상품", "price": 5000, "rating": 4.6, "review_count": 800, "delivery_info": "새벽배송"},
                {"product_name": "B상품", "price": 3500, "rating": 4.7, "review_count": 1200, "delivery_info": "일반배송 3-4일"},
                {"product_name": "C상품", "price": 4200, "rating": 4.3, "review_count": 400, "delivery_info": "일반배송"},
            ],
            "condition": "빠른배송",
            "keywords": ["상품"],
            "intent": "buy",
        },
        "output": {
            "expected_rank1": "A상품",
            "reason": "빠른배송 조건에서 delivery 가중치 35% → 새벽배송인 A상품이 1위여야 한다.",
        },
    },
    # 리뷰좋은 조건 → review_score 가중치 최고
    {
        "input": {
            "candidates": [
                {"product_name": "A상품", "price": 12000, "rating": 3.5, "review_count": 100, "delivery_info": "일반배송"},
                {"product_name": "B상품", "price": 9000, "rating": 4.9, "review_count": 15000, "delivery_info": "로켓배송"},
                {"product_name": "C상품", "price": 7000, "rating": 4.1, "review_count": 500, "delivery_info": "일반배송"},
            ],
            "condition": "리뷰좋은",
            "keywords": ["상품"],
            "intent": "buy",
        },
        "output": {
            "expected_rank1": "B상품",
            "reason": "리뷰좋은 조건에서 review 가중치 35% → 평점(4.9) + 리뷰수(15000) 최고인 B상품이 1위여야 한다.",
        },
    },
    # 재구매 intent → repurchase_match_score 가중치 최고
    {
        "input": {
            "candidates": [
                {"product_name": "풀무원 두부", "price": 2200, "rating": 4.5, "review_count": 2000, "delivery_info": "로켓배송"},
                {"product_name": "CJ 두부", "price": 1900, "rating": 4.3, "review_count": 800, "delivery_info": "일반배송"},
                {"product_name": "비비고 두부", "price": 2500, "rating": 4.7, "review_count": 3000, "delivery_info": "로켓배송"},
            ],
            "condition": None,
            "keywords": ["두부"],
            "intent": "reorder",
            "purchase_histories": [
                {"product_name_snapshot": "풀무원 두부", "category_snapshot": "식품"}
            ],
        },
        "output": {
            "expected_rank1": "풀무원 두부",
            "reason": "reorder intent에서 repurchase_match 가중치 35% → 구매 이력과 일치하는 풀무원 두부가 1위여야 한다.",
        },
    },
    # 조건 없음 → 기본 가중치 (keyword 25%, price 20%, delivery 20%, review 20%, repurchase 15%)
    {
        "input": {
            "candidates": [
                {"product_name": "사과 1kg", "price": 8900, "rating": 4.6, "review_count": 1500, "delivery_info": "로켓배송"},
                {"product_name": "사과 2kg", "price": 15000, "rating": 4.4, "review_count": 800, "delivery_info": "일반배송"},
                {"product_name": "사과 선물세트", "price": 35000, "rating": 4.8, "review_count": 3000, "delivery_info": "로켓배송"},
            ],
            "condition": None,
            "keywords": ["사과"],
            "intent": "buy",
        },
        "output": {
            "expected_rank1": "사과 1kg",
            "reason": "기본 가중치에서 키워드 매칭 + 적정 가격 + 빠른배송 + 높은 리뷰를 고루 갖춘 상품이 1위여야 한다.",
        },
    },
]


def _recreate_dataset(client: Client, name: str, description: str, examples: list[dict]) -> None:
    existing = list(client.list_datasets(dataset_name=name))
    if existing:
        client.delete_dataset(dataset_id=existing[0].id)
        print(f"  기존 '{name}' 삭제")

    dataset = client.create_dataset(dataset_name=name, description=description)
    for i, ex in enumerate(examples, start=1):
        client.create_example(
            inputs=ex["input"],
            outputs=ex["output"],
            dataset_id=dataset.id,
        )
        label = ex["input"].get("user_input") or ex["input"].get("keywords") or f"example-{i}"
        print(f"    [{i:02d}/{len(examples)}] {str(label)[:40]}")
    print(f"  ✓ '{name}' 생성 완료 ({len(examples)}개)")


def main():
    api_key = os.getenv("LANGSMITH_API_KEY")
    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    if not api_key:
        print("ERROR: LANGSMITH_API_KEY가 없습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    client = Client(api_key=api_key, api_url=endpoint)

    print("=== LangSmith Dataset 일괄 생성 ===\n")

    print("[1/3] Intent Agent Dataset")
    _recreate_dataset(
        client, INTENT_DATASET_NAME,
        "Intent Agent 평가용. 사용자 발화 → intent/keywords/condition 정확도 측정.",
        INTENT_EXAMPLES,
    )

    print("\n[2/3] Product Agent Dataset")
    _recreate_dataset(
        client, PRODUCT_DATASET_NAME,
        "Product Agent 평가용. 검색 결과 + 조건 → 올바른 상품 추천 여부 측정.",
        PRODUCT_EXAMPLES,
    )

    print("\n[3/3] Recommendation Scoring Dataset")
    _recreate_dataset(
        client, SCORING_DATASET_NAME,
        "추천 스코어링 평가용. 조건별 가중치에 따라 올바른 순위가 나오는지 측정.",
        SCORING_EXAMPLES,
    )

    print(f"\n=== 완료! LangSmith에서 확인: {LANGSMITH_UI} ===")
    print("  Datasets 탭 → intent-agent-eval, product-agent-eval, recommendation-scoring-eval")


if __name__ == "__main__":
    main()

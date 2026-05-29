"""
ddalangoo LangSmith 통합 파이프라인.

실행:
    cd backend
    python langsmith_pipeline.py

    # 프로덕션 low_confidence 수동 태깅:
    python langsmith_pipeline.py --monitor

단계:
  1. [Tracing]     환경변수 확인 + LangSmith 프로젝트 연결 검증 (실패 시 즉시 종료)
  2. [Dataset]     intent-agent-eval / product-agent-eval 업로드 (존재하면 skip)
  3. [Evaluator]   채점기 정의 (intent_match, keyword_coverage, quantity_match)
  4. [Experiments] evaluate() 실행 + 결과 URL 출력
  5. [Prompt Hub]  INTENT / PRODUCT / PLATFORM 프롬프트 happypot01/... 에 push
  6. [Monitoring]  low_confidence 자동 태깅 규칙 등록
"""

import os
import sys

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

_VENDOR = os.path.join(_HERE, "vendor", "ddalangoo-langgraph")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

# LangSmith 환경변수는 LangChain import 전에 세팅해야 트레이싱이 활성화됨
from dotenv import load_dotenv
load_dotenv(os.path.join(_HERE, ".env"))

os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGSMITH_PROJECT", "ddalangoo")

# ── 상수 ──────────────────────────────────────────────────────────────────────
LANGSMITH_UI  = "https://smith.langchain.com"
HUB_OWNER     = "happypot01"
PROJECT_NAME  = os.environ.get("LANGSMITH_PROJECT", "ddalangoo")
PROMPT_VERSION = "v1.0.0"

# ══════════════════════════════════════════════════════════════════════════════
# Dataset 예시
# ══════════════════════════════════════════════════════════════════════════════
INTENT_EVAL_DATASET = [
    # 1. 기본 구매 + 수량 명시
    {
        "input":  {"user_input": "우유 두 개 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["우유"], "quantity": 2, "condition": None, "needs_clarification": False},
    },
    # 2. 구매 + 조건 + 제외 브랜드
    {
        "input":  {"user_input": "풀무원 말고 CJ 두부 최저가로 찾아줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["CJ", "두부"], "exclude_keywords": ["풀무원"], "condition": "최저가", "needs_clarification": False},
    },
    # 3. pending=product_confirm → "응" → confirm
    {
        "input":  {"user_input": "응 그걸로 해줘", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "confirm", "keywords": [], "quantity": None, "needs_clarification": False},
    },
    # 4. pending=quantity_confirm → 한국어 수량 → confirm + quantity 필수
    {
        "input":  {"user_input": "세 개요", "stage": "product_confirming", "pending_action": "quantity_confirm"},
        "output": {"intent": "confirm", "quantity": 3, "needs_clarification": False},
    },
    # 5. 상품명 속 숫자는 quantity 아님 ("10구"는 규격, "두 판"이 수량)
    {
        "input":  {"user_input": "계란 10구짜리 두 판 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["계란"], "quantity": 2, "needs_clarification": False},
    },
    # 6. "다른 거 보여줘" → next (deny 아님)
    {
        "input":  {"user_input": "다른 거 보여줘", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "next", "needs_clarification": False},
    },
    # 7. pending 없이 "응" → unclear
    {
        "input":  {"user_input": "응", "stage": "idle", "pending_action": None},
        "output": {"intent": "unclear", "needs_clarification": True},
    },
    # 8. 플랫폼 비교 + 음식 키워드
    {
        "input":  {"user_input": "쿠팡이랑 마켓컬리에서 삼겹살 가격 비교해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "compare_platforms", "keywords": ["삼겹살"], "target_platforms": ["쿠팡", "마켓컬리"], "needs_clarification": False},
    },
    # 9. 재주문 + 음식
    {
        "input":  {"user_input": "저번에 시킨 우유 똑같이 다시 주문해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "reorder", "keywords": ["우유"], "needs_clarification": False},
    },
    # 10. 조건만 있고 상품명 없음 → needs_clarification
    {
        "input":  {"user_input": "신선한 걸로 찾아줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "needs_clarification": True},
    },
    # 11. 빠른배송 조건 + 음식
    {
        "input":  {"user_input": "소고기 빠른배송으로 주문해줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["소고기"], "condition": "빠른배송", "needs_clarification": False},
    },
    # 12. 리뷰 조건 + 음식
    {
        "input":  {"user_input": "리뷰 좋은 김치 사줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["김치"], "condition": "리뷰좋은", "needs_clarification": False},
    },
    # 13. 거절 → deny
    {
        "input":  {"user_input": "아니 다른 걸로 보여줘", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "deny", "needs_clarification": False},
    },
    # 14. 수량 변경
    {
        "input":  {"user_input": "다섯 개로 바꿔줘", "stage": "product_confirming", "pending_action": "product_confirm"},
        "output": {"intent": "quantity_change", "quantity": 5, "needs_clarification": False},
    },
    # 15. 가성비 + 음식
    {
        "input":  {"user_input": "가성비 좋은 참치캔 찾아줘", "stage": "idle", "pending_action": None},
        "output": {"intent": "buy", "keywords": ["참치캔"], "condition": "가성비", "needs_clarification": False},
    },
]

PRODUCT_EVAL_DATASET = [
    # 1. 최저가 조건 (선호도 없음) → 가장 저렴한 상품이 1위
    {
        "input": {
            "keywords": ["계란"], "condition": "최저가", "intent": "buy",
            "recommendation_context": {
                "preference_context": {
                    "summary": "선호 정보 없음 (구매이력 부족)",
                    "keyword_summary": "",
                }
            },
            "search_results": [
                {"product_name": "풀무원 목초란 10구", "price": 4200, "rating": 4.6, "review_count": 1800, "delivery": "로켓배송", "product_url": "https://a.com/1", "platform": "coupang"},
                {"product_name": "동물복지 유정란 15구","price": 6800, "rating": 4.8, "review_count": 920,  "delivery": "일반배송", "product_url": "https://a.com/2", "platform": "naver"},
                {"product_name": "국산 달걀 30구",     "price": 3900, "rating": 4.1, "review_count": 540,  "delivery": "일반배송", "product_url": "https://a.com/3", "platform": "naver"},
            ],
        },
        "output": {"expected_rank1_product": "국산 달걀 30구"},
    },
    # 2. 빠른배송 조건 (선호도 없음) → 로켓/새벽배송 상품이 1위
    {
        "input": {
            "keywords": ["우유"], "condition": "빠른배송", "intent": "buy",
            "recommendation_context": {
                "preference_context": {
                    "summary": "선호 정보 없음 (구매이력 부족)",
                    "keyword_summary": "",
                }
            },
            "search_results": [
                {"product_name": "서울우유 1L",  "price": 2800, "rating": 4.5, "review_count": 980,  "delivery": "로켓배송", "product_url": "https://b.com/1", "platform": "coupang"},
                {"product_name": "매일우유 900ml","price": 2500, "rating": 4.1, "review_count": 420,  "delivery": "일반배송", "product_url": "https://b.com/2", "platform": "naver"},
                {"product_name": "남양우유 1L",  "price": 2700, "rating": 4.3, "review_count": 610,  "delivery": "새벽배송", "product_url": "https://b.com/3", "platform": "kurly"},
            ],
        },
        "output": {"expected_rank1_product": "서울우유 1L"},
    },
    # 3. 선호도 반영 → 브랜드 선호가 있을 때 condition보다 우선
    {
        "input": {
            "keywords": ["두부"], "condition": None, "intent": "buy",
            "recommendation_context": {
                "preference_context": {
                    "summary": "풀무원 제품을 반복 구매한 이력이 있음",
                    "keyword_summary": "두부: 풀무원 선호, 가격대 2000~4000원",
                }
            },
            "search_results": [
                {"product_name": "CJ 행복한콩 두부 300g",  "price": 1500, "rating": 4.2, "review_count": 210,  "delivery": "일반배송", "product_url": "https://c.com/1", "platform": "naver"},
                {"product_name": "풀무원 국산콩 두부 400g", "price": 2800, "rating": 4.7, "review_count": 3200, "delivery": "로켓배송", "product_url": "https://c.com/2", "platform": "coupang"},
                {"product_name": "자연두부 순두부 350g",    "price": 1200, "rating": 3.9, "review_count": 88,   "delivery": "일반배송", "product_url": "https://c.com/3", "platform": "naver"},
            ],
        },
        "output": {"expected_rank1_product": "풀무원 국산콩 두부 400g"},
    },
    # 4. 리뷰 조건 + 선호도 혼합 → 리뷰 수 가장 많은 상품
    {
        "input": {
            "keywords": ["김치"], "condition": "리뷰좋은", "intent": "buy",
            "recommendation_context": {
                "preference_context": {
                    "summary": "김치 구매이력 있음, 가격 민감",
                    "keyword_summary": "김치: 종갓집 선호",
                }
            },
            "search_results": [
                {"product_name": "종갓집 포기김치 3kg",  "price": 28000, "rating": 4.5, "review_count": 4100, "delivery": "일반배송", "product_url": "https://d.com/1", "platform": "coupang"},
                {"product_name": "비비고 썰은김치 1kg",  "price": 9800,  "rating": 4.8, "review_count": 8700, "delivery": "로켓배송", "product_url": "https://d.com/2", "platform": "coupang"},
                {"product_name": "하선정 총각김치 2kg",  "price": 18000, "rating": 4.3, "review_count": 620,  "delivery": "일반배송", "product_url": "https://d.com/3", "platform": "naver"},
            ],
        },
        "output": {"expected_rank1_product": "비비고 썰은김치 1kg"},
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# 유틸 출력
# ══════════════════════════════════════════════════════════════════════════════
def _step(n: int, name: str):
    print(f"\n{'='*62}")
    print(f"  [{n}] {name}")
    print("="*62)


def _ok(msg: str):
    print(f"  ✓ {msg}")


def _fail(msg: str):
    print(f"  ✗ {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Tracing
# ══════════════════════════════════════════════════════════════════════════════
def run_tracing():
    _step(1, "Tracing — 환경변수 확인 + LangSmith 연결 검증")

    api_key = os.environ.get("LANGSMITH_API_KEY")
    tracing = os.environ.get("LANGCHAIN_TRACING_V2")
    project = os.environ.get("LANGSMITH_PROJECT")

    if not api_key:
        _fail("LANGSMITH_API_KEY 없음. backend/.env 에 추가하세요:")
        _fail("  LANGSMITH_API_KEY=ls__...")
        _fail("  LANGCHAIN_TRACING_V2=true")
        _fail("  LANGSMITH_PROJECT=ddalangoo")
        sys.exit(1)

    _ok(f"LANGSMITH_API_KEY : {api_key[:8]}...")
    _ok(f"LANGCHAIN_TRACING_V2 : {tracing}")
    _ok(f"LANGSMITH_PROJECT : {project}")

    from langsmith import Client
    client = Client(api_key=api_key)

    try:
        existing = {p.name for p in client.list_projects()}
        if PROJECT_NAME not in existing:
            client.create_project(PROJECT_NAME)
            _ok(f"프로젝트 생성: {PROJECT_NAME}")
        else:
            _ok(f"프로젝트 연결 확인: {PROJECT_NAME}")
    except Exception as e:
        _fail(f"LangSmith 연결 실패: {e}")
        sys.exit(1)

    _ok(f"UI: {LANGSMITH_UI}")
    return client


# ══════════════════════════════════════════════════════════════════════════════
# 2. Dataset
# ══════════════════════════════════════════════════════════════════════════════
def _upload_dataset(client, name: str, description: str, examples: list, reset: bool = False):
    try:
        existing = list(client.list_datasets(dataset_name=name))
        if existing:
            if not reset:
                _ok(f"이미 존재 — skip: {name}  (재생성하려면 --reset 옵션 사용)")
                return
            client.delete_dataset(dataset_id=existing[0].id)
            _ok(f"기존 Dataset 삭제: {name}")

        dataset = client.create_dataset(dataset_name=name, description=description)
        for ex in examples:
            client.create_example(
                inputs=ex["input"],
                outputs=ex["output"],
                dataset_id=dataset.id,
            )
        _ok(f"업로드 완료: {name} ({len(examples)}개 예시)")
    except Exception as e:
        _fail(f"{name} 업로드 실패: {e}")


def run_dataset(client, reset: bool = False):
    _step(2, "Dataset — LangSmith Dataset 업로드")
    _upload_dataset(
        client,
        name="intent-agent-eval",
        description="Intent Agent 평가: intent/keyword/quantity/condition 정확도 (음식 도메인)",
        examples=INTENT_EVAL_DATASET,
        reset=reset,
    )
    _upload_dataset(
        client,
        name="product-agent-eval",
        description="Product Agent 평가: 1순위 상품 정확도 + 설명 품질",
        examples=PRODUCT_EVAL_DATASET,
        reset=reset,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Evaluators (intent_agent)
# ══════════════════════════════════════════════════════════════════════════════
def eval_intent_match(run, example):
    """intent 정확 일치 여부 (0 or 1)."""
    predicted = (run.outputs or {}).get("intent")
    expected  = (example.outputs or {}).get("intent")
    return {"key": "intent_match", "score": 1.0 if predicted == expected else 0.0}


def eval_keyword_coverage(run, example):
    """정답 keyword 중 예측에 포함된 비율 (0~1)."""
    predicted = set((run.outputs or {}).get("keywords", []))
    expected  = set((example.outputs or {}).get("keywords", []))
    if not expected:
        return {"key": "keyword_coverage", "score": 1.0}
    score = len(predicted & expected) / len(expected)
    return {"key": "keyword_coverage", "score": round(score, 4)}


def eval_quantity_match(run, example):
    """quantity 일치 여부 (null끼리도 일치로 처리, 0 or 1)."""
    predicted = (run.outputs or {}).get("quantity")
    expected  = (example.outputs or {}).get("quantity")
    return {"key": "quantity_match", "score": 1.0 if predicted == expected else 0.0}


def eval_clarification_match(run, example):
    """needs_clarification True/False 예측이 정답과 일치하는가 (0 or 1)."""
    predicted = (run.outputs or {}).get("needs_clarification", False)
    expected  = (example.outputs or {}).get("needs_clarification", False)
    return {"key": "clarification_match", "score": 1.0 if predicted == expected else 0.0}


# ══════════════════════════════════════════════════════════════════════════════
# 4. Experiments
# ══════════════════════════════════════════════════════════════════════════════
def _intent_target(inputs: dict) -> dict:
    """Dataset 입력 → Intent Agent 실행 → 평가용 출력 반환."""
    from langchain_core.messages import HumanMessage
    from src.agents.intent_agent import intent_agent_node

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
        # 채점 대상
        "intent":              result.get("intent"),
        "keywords":            result.get("keywords", []),
        "condition":           result.get("condition"),
        "quantity":            result.get("quantity"),
        "needs_clarification": result.get("needs_clarification", False),
        # 디버깅용 추가 필드 (LangSmith Output 탭에서 확인 가능)
        "confidence":          result.get("confidence"),
        "immediate_response":  result.get("immediate_response"),
        "exclude_keywords":    result.get("exclude_keywords", []),
        "override_platform":   result.get("override_platform"),
    }


def _product_target(inputs: dict) -> dict:
    """Dataset 입력 → Product Agent 실행 → 평가용 출력 반환.

    @traceable 로 감싸 LangSmith에 LLM 호출 / rank_products 툴 / preference 반영 과정을
    nested run(자식 run)으로 기록한다.
    """
    from langsmith import traceable
    from langchain_core.messages import HumanMessage
    from src.agents.product_agent import product_agent_node

    @traceable(name="product_agent_eval", tags=["eval", PROMPT_VERSION])
    def _run(inputs: dict) -> dict:
        preference_context = (
            inputs.get("recommendation_context", {}).get("preference_context") or {}
        )
        state = {
            "messages":              [HumanMessage(content=" ".join(inputs.get("keywords", [])))],
            "search_results":        inputs.get("search_results", []),
            "recommended_products":  [],
            "selected_product":      None,
            "current_product_index": 0,
            "condition":             inputs.get("condition"),
            "quantity":              None,
            "keywords":              inputs.get("keywords", []),
            "intent":                inputs.get("intent", "buy"),
            "pending_action":        None,
            "recommendation_context": inputs.get("recommendation_context", {}),
        }
        result   = product_agent_node(state)
        selected = result.get("selected_product") or {}
        return {
            # 채점 대상
            "rank1_product": selected.get("product_name") or selected.get("name"),
            "explanation":   result.get("explanation", ""),
            # 디버깅용: 선호도 반영 과정 추적
            "preference_summary":  preference_context.get("summary", ""),
            "preference_keywords": preference_context.get("keyword_summary", ""),
            "candidates_count":    len(inputs.get("search_results", [])),
            "all_ranked_products": [
                p.get("product_name") for p in (result.get("recommended_products") or [])
            ],
        }

    return _run(inputs)


def _eval_rank1_match(run, example):
    """1순위 상품이 정답과 일치하는가."""
    predicted = (run.outputs or {}).get("rank1_product", "")
    expected  = (example.outputs or {}).get("expected_rank1_product", "")
    return {"key": "rank1_match", "score": 1.0 if predicted == expected else 0.0}


def _eval_explanation_quality(run, example):
    """LLM-as-judge로 설명 품질 0~1 채점."""
    from langchain_openai import ChatOpenAI

    explanation = (run.outputs or {}).get("explanation", "")
    condition   = example.inputs.get("condition") or "없음"
    keywords    = example.inputs.get("keywords", [])

    if not explanation:
        return {"key": "explanation_quality", "score": 0.0}

    prompt = f"""쇼핑 어시스턴트의 상품 추천 설명 품질을 평가하세요.

검색 조건: {condition}
검색 키워드: {keywords}
추천 설명: {explanation}

평가 기준:
1. condition에 맞는 추천 이유가 포함되어 있는가?
2. 키워드와 관련된 상품명이 언급되는가?
3. 음성 출력에 적합한 자연스러운 한국어인가?

0.0~1.0 사이 숫자 하나만 반환. 예: 0.8"""

    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        score = float(llm.invoke(prompt).content.strip())
        score = max(0.0, min(1.0, score))
    except Exception:
        score = 0.5
    return {"key": "explanation_quality", "score": round(score, 4)}


def run_experiments():
    _step(3, "Evaluator 정의 확인")
    _ok("intent_match          — intent 정확 일치 (0 or 1)")
    _ok("keyword_coverage      — 정답 keyword 포함률 (0~1)")
    _ok("quantity_match        — quantity 일치 (null 포함, 0 or 1)")
    _ok("clarification_match   — needs_clarification 일치 (0 or 1)")
    _ok("rank1_match           — 1순위 상품 정확도 (product_agent)")
    _ok("explanation_quality   — LLM-as-judge 설명 품질 (product_agent)")

    _step(4, "Experiments — evaluate() 실행")

    from langsmith import evaluate as ls_evaluate

    # ── Intent Agent ──
    try:
        print("\n  [intent-agent-eval] 실행 중...")
        ls_evaluate(
            _intent_target,
            data="intent-agent-eval",
            evaluators=[eval_intent_match, eval_keyword_coverage, eval_quantity_match, eval_clarification_match],
            experiment_prefix="intent-agent",
            metadata={"model": "gpt-4o-mini", "prompt_version": PROMPT_VERSION},
        )
        _ok("intent-agent-eval 완료")
    except Exception as e:
        _fail(f"intent-agent-eval 실패: {e}")

    # ── Product Agent ──
    try:
        print("\n  [product-agent-eval] 실행 중...")
        ls_evaluate(
            _product_target,
            data="product-agent-eval",
            evaluators=[_eval_rank1_match, _eval_explanation_quality],
            experiment_prefix="product-agent",
            metadata={"model": "claude-sonnet-4-6", "prompt_version": PROMPT_VERSION},
        )
        _ok("product-agent-eval 완료")
    except Exception as e:
        _fail(f"product-agent-eval 실패: {e}")

    _ok(f"결과 확인: {LANGSMITH_UI} → 프로젝트 {PROJECT_NAME} → Experiments 탭")


# ══════════════════════════════════════════════════════════════════════════════
# 5. Prompt Hub
# ══════════════════════════════════════════════════════════════════════════════
def run_prompt_hub(client):
    _step(5, f"Prompt Hub — {HUB_OWNER}/... push ({PROMPT_VERSION})")

    try:
        from langchain_core.prompts import ChatPromptTemplate
        from src.prompts.intent_prompt import INTENT_AGENT_PROMPT
        from src.prompts.product_prompt import PRODUCT_RANK_PROMPT, PRODUCT_EXPLAIN_PROMPT
        from src.prompts.platform_prompt import PLATFORM_AGENT_PROMPT
    except ImportError as e:
        _fail(f"import 실패: {e}")
        return

    entries = [
        (
            "intent-prompt",
            ChatPromptTemplate.from_messages([("system", INTENT_AGENT_PROMPT)]),
            "intent",
        ),
        (
            "product-prompt",
            ChatPromptTemplate.from_messages([
                ("system", f"# Rank Prompt\n{PRODUCT_RANK_PROMPT}\n\n# Explain Prompt\n{PRODUCT_EXPLAIN_PROMPT}"),
            ]),
            "product",
        ),
        (
            "platform-prompt",
            ChatPromptTemplate.from_messages([("system", PLATFORM_AGENT_PROMPT)]),
            "platform",
        ),
    ]

    for repo_name, prompt, label in entries:
        try:
            # owner 접두사 없이 push → SDK가 현재 인증된 계정(happypot01)으로 자동 귀속
            client.push_prompt(repo_name, object=prompt, is_public=True, tags=[PROMPT_VERSION])
            _ok(f"{label}: {HUB_OWNER}/{repo_name} push 완료 (태그: {PROMPT_VERSION})")
        except Exception as e:
            _fail(f"{label} push 실패: {e}")

    # 다음 버전 업: 프롬프트 파일 수정 후 PROMPT_VERSION = "v1.1.0" 으로 바꾸고 재실행
    _ok(f"버전 업: PROMPT_VERSION 상수를 'v1.1.0' 등으로 올린 뒤 재실행하면 새 커밋으로 저장됨")
    _ok(f"Hub 확인: {LANGSMITH_UI}/hub")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Online Monitoring
# ══════════════════════════════════════════════════════════════════════════════
def run_monitoring(client):
    _step(6, "Online Monitoring — low_confidence 자동 태깅 규칙 등록")

    import requests

    api_key  = os.environ.get("LANGSMITH_API_KEY")
    endpoint = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    try:
        project = next(
            (p for p in client.list_projects() if p.name == PROJECT_NAME),
            None,
        )
        if not project:
            _fail(f"프로젝트 '{PROJECT_NAME}' 없음")
            return

        project_id = str(project.id)
        headers = {"x-api-key": api_key, "Content-Type": "application/json"}

        rule_payload = {
            "display_name": "low_confidence_tagger",
            "sampling_rate": 1.0,
            "filter": (
                'and(or(eq(outputs.intent, "unclear"),'
                'lt(outputs.confidence, 0.5)),'
                'neq(outputs.intent, null))'
            ),
            "actions": [{"type": "label", "value": "low_confidence"}],
        }

        # LangSmith Automation Rules API (v1)
        resp = requests.post(
            f"{endpoint}/api/v1/automation/rules",
            headers=headers,
            json={**rule_payload, "project_id": project_id},
            timeout=10,
        )

        if resp.status_code in (200, 201):
            _ok("Automation rule 등록 완료: low_confidence_tagger")
            _ok("기준: confidence < 0.5 또는 intent == 'unclear' → 라벨: low_confidence")
        elif resp.status_code == 409:
            _ok("Automation rule 이미 존재 — skip")
        else:
            # Automation API는 플랜에 따라 지원 여부가 다를 수 있음 → UI 안내로 fallback
            _fail(f"Automation API 미지원 ({resp.status_code}) — UI에서 직접 설정해주세요:")
            _ok("  LangSmith → Projects → ddalangoo → Automations → + New Rule")
            _ok("  Filter:  and(eq(outputs.intent,'unclear'),lt(outputs.confidence,0.5))")
            _ok("  Action:  Add Label → low_confidence")
            _ok("")
            _ok("  또는 아래 명령으로 수동 태깅 (프로덕션 운영 중 주기적 실행):")
            _ok("  python langsmith_pipeline.py --monitor")

        _ok(f"확인: {LANGSMITH_UI} → {PROJECT_NAME} → Runs → 필터: low_confidence")

    except Exception as e:
        _fail(f"Monitoring 설정 실패: {e}")
        _ok("수동 태깅: python langsmith_pipeline.py --monitor")


def tag_low_confidence_runs(client, hours: int = 24):
    """
    최근 N시간 내 프로덕션 트레이스 중 low_confidence 케이스에 feedback 태그 추가.
    Automation rule 대신 수동/정기 실행 용도.

    사용:
        python langsmith_pipeline.py --monitor
    """
    from datetime import datetime, timedelta, timezone

    print(f"\n[Monitoring] 최근 {hours}시간 내 low_confidence Run 스캔 중...")

    try:
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        runs = client.list_runs(
            project_name=PROJECT_NAME,
            start_time=start_time,
            run_type="chain",
        )

        tagged = 0
        for run in runs:
            outputs    = run.outputs or {}
            confidence = outputs.get("confidence", 1.0)
            intent     = outputs.get("intent", "")

            if (confidence is not None and confidence < 0.5) or intent == "unclear":
                client.create_feedback(
                    run_id=run.id,
                    key="low_confidence",
                    score=1.0,
                    comment=f"confidence={confidence}, intent={intent}",
                )
                tagged += 1

        _ok(f"{tagged}개 Run에 low_confidence 태그 추가")
    except Exception as e:
        _fail(f"수동 태깅 실패: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "█" * 62)
    print("  ddalangoo LangSmith Pipeline")
    print("█" * 62)

    if "--monitor" in sys.argv:
        from langsmith import Client
        _client = Client(api_key=os.environ.get("LANGSMITH_API_KEY"))
        tag_low_confidence_runs(_client)
        sys.exit(0)

    # --step N 으로 특정 단계만 실행 가능
    # 예: python langsmith_pipeline.py --step 5
    step_arg = None
    if "--step" in sys.argv:
        idx = sys.argv.index("--step")
        if idx + 1 < len(sys.argv):
            step_arg = int(sys.argv[idx + 1])

    _reset = "--reset" in sys.argv
    _client = run_tracing()  # 1. 항상 실행 (인증 필요)

    if step_arg is None or step_arg == 2:
        run_dataset(_client, reset=_reset)
    if step_arg is None or step_arg in (3, 4):
        run_experiments()
    if step_arg is None or step_arg == 5:
        run_prompt_hub(_client)
    if step_arg is None or step_arg == 6:
        run_monitoring(_client)

    print("\n" + "█" * 62)
    print("  파이프라인 완료")
    print(f"  LangSmith: {LANGSMITH_UI}")
    print("█" * 62 + "\n")

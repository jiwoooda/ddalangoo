"""
Intent Agent Node.

역할: 사용자 발화 → intent + slot 추출.
with_structured_output(Pydantic)으로 스키마를 강제해 누락 방지.
"""
import re
from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.errors import NodeError
from langgraph.runtime import Runtime
from langgraph.types import Command

from configs.llm_config import get_llm
from src.state.schema import ShoppingState
from src.state.node_inputs import IntentAgentInput, IntentAgentUpdate
from src.prompts.intent_prompt import INTENT_AGENT_PROMPT
from src.utils.agent_logger import agent_logger
from src.utils.retry import FailureClass, classify_failure
from src.utils.search_keywords import normalize_search_keywords

IntentType = Literal[
    "buy", "reorder", "confirm", "deny", "next", "refine",
    "compare_platforms", "quantity_change", "address_change",
    "option_select", "ask", "cancel", "unclear",
]

ConditionType = Literal["최저가", "가성비", "빠른배송", "인기순", "무료배송", "리뷰좋은"]

_KR_NUM = {
    "하나": 1, "한": 1, "일": 1,
    "둘": 2, "두": 2,
    "셋": 3, "세": 3,
    "넷": 4, "네": 4,
    "다섯": 5, "오": 5,
    "여섯": 6, "육": 6,
    "일곱": 7, "칠": 7,
    "여덟": 8, "팔": 8,
    "아홉": 9, "구": 9,
    "열": 10, "십": 10,
    "스물": 20, "스무": 20, "이십": 20,
}

def _looks_like_quantity_reply(text: str) -> bool:
    """STT 텍스트가 수량 답변처럼 보이는지 판단."""
    import re
    t = text.strip()
    if re.fullmatch(r'\d+', t):
        return True
    units = r'(개|인분|명|병|통|팩|봉|캔|묶음|박스|세트)'
    kr_nums = r'(하나|한|둘|두|셋|세|넷|네|다섯|여섯|일곱|여덟|아홉|열|\d+)'
    return bool(re.search(kr_nums + r'\s*' + units, t))


def _normalize_keyword_tokens(keywords: list[str]) -> list[str]:
    """중복·공백 제거 및 빈 문자열 필터."""
    return normalize_search_keywords(keywords)


_STOP_WORDS = frozenset({
    "사줘", "사줄래", "사주세요", "사고싶어", "사고 싶어", "구매", "구매해줘", "주문",
    "주문해줘", "찾아줘", "보여줘", "주세요", "해줘", "해줄래", "싶어", "좀", "저",
    "제", "그냥", "그거", "이거", "저거",
    # 재구매 지시/시간 표현 — 상품명이 아닌데 길이(>=2) 조건을 통과해 keywords로
    # 잘못 살아남으면 _is_ambiguous_reorder/_should_force_reorder의 "keywords가
    # 비어있어야 모호 재구매로 판정" 로직이 깨진다 (실측: "저번에 샀던 거 사줘"가
    # keywords=["저번에","샀던"]로 뽑혀 재구매 모호 처리를 못 타고 일반 상품
    # 검색으로 새어나간 사례).
    "저번에", "지난번에", "예전에", "샀던", "다시", "똑같이", "재주문",
})

def _fallback_search_keywords(user_input: str) -> list[str]:
    """LLM이 빈 keywords 반환 시 raw text에서 단순 휴리스틱 추출."""
    import re
    tokens = re.split(r'[\s,]+', user_input.strip())
    result = [t for t in tokens if t and t not in _STOP_WORDS and len(t) >= 2]
    return result[:3]


_BUY_TRIGGERS = frozenset({
    "사줘", "사줄래", "사주세요", "구매해", "구매해줘", "주문해",
    "사고싶어", "사고 싶어", "사 줘",
})
_REORDER_SIGNALS = frozenset({"저번에", "지난번에", "재주문", "똑같이 다시", "예전에 산"})

_DISMISSIVE_PHRASES = frozenset({
    "아무거나", "아무거나요", "암거나", "아무렇게나",
    "상관없어요", "상관없어", "상관 없어요", "상관 없어",
    "편한대로", "편한 대로", "알아서", "알아서요", "알아서 해주세요", "알아서 해줘",
})

def _should_force_buy_from_freeform(user_input: str, intent: str, stage: str) -> bool:
    """idle 상태에서 buy 트리거가 있는데 LLM이 다른 intent를 뽑았을 때 buy로 교정.
    reorder는 교정 대상에서 제외 — 재구매 신호가 buy 트리거보다 우선."""
    if intent in ("buy", "reorder") or stage != "idle":
        return False
    return any(t in user_input for t in _BUY_TRIGGERS)

def _should_force_reorder(user_input: str, intent: str, stage: str, keywords: list) -> bool:
    """재구매 신호 + 상품명이 있는데 LLM이 buy로 잘못 분류했을 때 reorder로 교정."""
    if intent == "reorder" or stage != "idle":
        return False
    has_reorder_signal = any(t in user_input for t in _REORDER_SIGNALS)
    has_product = bool(keywords)
    return has_reorder_signal and has_product


def _should_force_recommendation_fallback(user_input: str, intent: str, stage: str, keywords: list) -> bool:
    """상품명 없이 '아무거나/상관없어요' 등으로 답하면, 계속 되묻는 대신
    프로필의 favorite_foods로 대신 채우도록 context_agent에 신호를 보낸다
    (실제 keywords 대입은 context_agent 담당 — 여기선 profile에 접근하지 않음).
    이미 keywords가 있으면(예: "딸기는 아무거나 괜찮아요") 그 자체로 충분한
    정보라 건드리지 않는다."""
    if intent != "buy" or stage not in ("idle", "searching") or keywords:
        return False
    text = user_input.strip()
    return any(p in text for p in _DISMISSIVE_PHRASES)


# product_confirm/cart_review는 intent="ask"가 되면 response_agent
# (_generate_qa_answer)로 안전하게 빠지는 기존 경로가 있다. address_confirm/
# payment_method_confirm/payment_password는 stage="payment_processing"이라
# route()가 intent와 무관하게 무조건 payment_agent로 보내는데, payment_agent가
# 이 셋에 대해서는 이제 intent="ask"를 직접 확인해 결제수단/배송 질문에
# 답하고 원래 pending_action을 그대로 유지한다(WON-19 Unit 4,
# src/payment/node.py::_answer_payment_flow_question) — 그 안전장치가 생기기
# 전까지는(Unit 3 당시) 이 셋을 일부러 뺐었다.
_PAYMENT_PENDING_TYPES = frozenset({
    "product_confirm", "cart_review",
    "address_confirm", "payment_method_confirm", "payment_password",
})


def _should_trust_ask_over_clarification(
    intent: str, needs_clarification: bool, clarification_reason: Optional[str],
    confidence: float, pending_type: str,
) -> bool:
    """결제 흐름 대기 중(product_confirm/cart_review/address_confirm/
    payment_method_confirm/payment_password) 사용자가 결제수단/배송/환불 같은
    질문을 하면, intent=ask는 정확히 분류하면서도 "나는 답을 모른다"는 이유로
    clarification_reason 없이 needs_clarification=true를 방어적으로 켜는
    경우가 실측 확인됐다(WON-19, fl-2026-08-27-001) — response_agent가 이미
    이런 질문에 답할 능력(_generate_qa_answer/_is_address_question)을 갖추고
    있는데, router.py::route()의 이른 needs_clarification 게이트가 stage-router
    (ask→response_agent 디스패치)보다 먼저 걸려 그 경로 자체를 못 타게 막는다.

    clarification_reason이 실제로 채워진 경우(LLM이 구체적 근거를 댄 경우)는
    건드리지 않는다 — 진짜 모호한 ask(예: "그거 얼마예요?"의 "그거"가 뭔지
    불명확한 경우)까지 덮어쓰면 안 되므로, "이유 없이 방어적으로 켠 경우"만
    좁게 교정한다."""
    return (
        intent == "ask"
        and needs_clarification
        and not clarification_reason
        and confidence >= 0.5
        and pending_type in _PAYMENT_PENDING_TYPES
    )


def _should_clear_existing_cart(intent: str, cart_operations: list[dict]) -> bool:
    """intent=buy 발화에 CLEAR_CART가 섞여 있으면("싹 다 비우고 계란만 담아")
    기존 장바구니를 비워야 한다는 신호다. cart_operations는 매 턴 intent_agent가
    다시 쓰는 필드라(recommend_from_profile과 동일 패턴) payment_agent의 Step 0가
    실제로 담기를 실행하는 시점(보통 2턴 뒤, "네" 확인 이후)엔 이미 사라지고
    없다 — 그래서 이 판단 결과를 intent_agent_node가 queue_clear_existing(턴을
    넘어 지속되는 필드)에 옮겨 담아 Step 0까지 전달한다."""
    if intent != "buy":
        return False
    return any(op.get("op") == "CLEAR_CART" for op in cart_operations)


def _split_multi_buy_queue(intent: str, cart_operations: list[dict]) -> Optional[dict]:
    """intent=buy 발화에 서로 다른 상품(ADD_ITEM)이 2개 이상 담겼으면("계란이랑
    참기름 사줘"), 이번 턴엔 첫 품목만 검색하고 전체 품목을 queue_items로 채워
    purchase_queue_agent가 이어받게 한다 — recipe_agent를 거치지 않고 곧장
    큐를 채운다(fl-2026-08-25-001 다음 단계, 설계 문서: radiant-questing-map.md
    Unit 4). ADD_ITEM이 0~1개면(대부분의 평범한 buy 요청) None을 반환해 기존
    keywords/quantity 처리를 그대로 둔다 — 회귀 없음.

    queue_items에는 첫 품목도 포함시킨다(current_queue_index=0으로 그 자리를
    가리킴) — recipe_agent의 Mode 1이 재료 목록 전체를 queue_items에 채우고
    idx=0에서 시작하는 것과 동일한 컨벤션. purchase_queue_agent의 advance_queue는
    "idx가 가리키는 품목이 방금 처리됨"을 전제로 다음 품목 이름을 안내하므로,
    첫 품목을 큐에서 빼놓으면(idx만 세팅) advance_queue가 "방금 담은 품목"
    이름을 알 방법이 없어진다 — 실측으로 확인된 버그, queue_items를 이 방식
    (전체 포함)으로 채워야 recipe 흐름과 완전히 같은 인덱싱 규칙을 공유한다."""
    if intent != "buy":
        return None
    add_ops = [op for op in cart_operations if op.get("op") == "ADD_ITEM"]
    if len(add_ops) < 2:
        return None
    first = add_ops[0]
    return {
        "keywords": [first["item"]],
        "quantity": first.get("quantity"),
        "queue_items": [
            {"name": op["item"], "quantity": op.get("quantity") or 1, "unit": "개"}
            for op in add_ops
        ],
        "current_queue_index": 0,
        "queue_source": "multi_buy",
    }


def _parse_quantity(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    text = str(v).strip()
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    for kr, num in sorted(_KR_NUM.items(), key=lambda x: -len(x[0])):
        if kr in text:
            return num
    return None


class CartOperation(BaseModel):
    """장바구니에 대한 개별 조작 하나. quantity_change가 "지목한 품목 하나의 수량을
    확정"만 표현할 수 있어(단일 keywords+quantity 스칼라), 여러 품목에 다른 조작이
    섞이거나(예: "딸기는 하나 더하고 우유는 2개 뺄게") 증감(relative)과 확정(absolute)을
    구분해야 하거나, "나머지는 다 빼고"처럼 장바구니를 통째로 비운 뒤 일부만 다시
    채우는 경우를 못 담는다 — 발화를 하나의 intent가 아니라 순서대로 적용되는 여러
    CartOperation으로 변환해 표현한다(파싱은 LLM, 실제 수량 계산/커밋은 코드가 전담).

    한 문장에 여러 operation이 나올 수 있고, 리스트 순서대로 적용된다 — 예:
    "다 빼고 우유 하나만" → [CLEAR_CART, SET_QUANTITY(item=우유, quantity=1)]."""
    op: Literal["ADD_ITEM", "REMOVE_ITEM", "SET_QUANTITY", "CHANGE_QUANTITY", "CLEAR_CART"] = Field(
        description="ADD_ITEM/SET_QUANTITY=해당 품목 수량을 quantity로 확정(최종 수량을 말한 경우). "
        "REMOVE_ITEM=해당 품목 완전 제거. CHANGE_QUANTITY=현재 수량에서 delta만큼 상대적으로 "
        "증감(증가는 양수, 감소는 음수 — 최종 수량이 아니라 증감량을 말한 경우). "
        "CLEAR_CART=그 시점까지의 장바구니를 통째로 비움(뒤에 오는 operation은 빈 장바구니에 적용됨)."
    )
    item: Optional[str] = Field(default=None, description="대상 품목을 가리키는 이름. CLEAR_CART는 불필요(null).")
    quantity: Optional[int] = Field(default=None, description="ADD_ITEM/SET_QUANTITY의 목표(최종) 수량.")
    delta: Optional[int] = Field(default=None, description="CHANGE_QUANTITY의 증감량. 늘리면 양수, 줄이면 음수.")


class IntentOutput(BaseModel):
    intent: IntentType = Field(description="사용자 의도")
    keywords: list[str] = Field(default_factory=list, description="검색할 상품명/카테고리/브랜드")
    exclude_keywords: list[str] = Field(default_factory=list, description="제외할 브랜드/플랫폼/상품명")
    negative_constraints: list[str] = Field(default_factory=list, description="자연어 제외 조건")
    quantity: Optional[int] = Field(
        default=None,
        description="명시된 수량만 정수로. 없으면 null.",
        json_schema_extra={"examples": [1, 2, 3, 5, 10]},
    )
    condition: Optional[ConditionType] = Field(default=None, description="검색 조건")
    recipe_dish: Optional[str] = Field(default=None, description="재료 구매 요리명 (예: 된장찌개). 직접 상품 구매면 null")
    recipe_people: Optional[int] = Field(default=None, description="인원수 (예: 4인 가족 → 4). 없으면 null")
    target_platforms: list[str] = Field(default_factory=list, description="비교 대상 플랫폼 목록")
    override_platform: Optional[str] = Field(default=None, description="명시적으로 지정한 단일 플랫폼")
    current_option_value: Optional[str] = Field(default=None, description="명시된 상품 옵션값")
    address_text: Optional[str] = Field(default=None, description="사용자가 말한 배송지 텍스트")
    needs_clarification: bool = Field(default=False, description="추가 정보가 필요하면 true")
    clarification_reason: Optional[str] = Field(default=None, description="needs_clarification=true일 때 이유")
    confidence: float = Field(default=0.95, description="의도 해석 확신도 0.0~1.0")
    immediate_response: str = Field(default="", description="음성 출력용 한 문장 응답")
    cart_operations: list[CartOperation] = Field(
        default_factory=list,
        description="장바구니에 대한 조작이 두 개 이상 섞였거나(품목별로 다른 조작), 장바구니를 "
        "통째로/부분적으로 비우거나, 최종 수량이 아니라 증감량을 말하는 등 단순 수량 확정 "
        "하나로 표현 안 될 때만 채운다. 단일 품목의 단순 수량 확정 하나뿐이면 비워두고 "
        "기존 keywords/quantity를 그대로 쓴다.",
    )


_llm = None
_structured_llm = None


def _get_llm():
    global _llm, _structured_llm
    if _llm is None:
        # retry_owner="application": 이 노드는 NODE_RETRY_POLICY로 재시도되므로
        # anthropic/openai SDK 자체 재시도는 꺼서 중첩 재시도를 막는다.
        _llm = get_llm("intent", temperature=0, retry_owner="application")
        # method="json_schema"(엄격 모드)는 IntentOutput처럼 필드/Optional/enum이
        # 많은 큰 스키마에서 "Schema is too complex" 에러로 API가 거부할 수 있어
        # 기본값(function_calling)을 쓴다. 작은 스키마(SafetySignalUpdate 등)엔
        # json_schema가 안전하니 거기선 그대로 유지.
        _structured_llm = _llm.with_structured_output(IntentOutput)
    return _structured_llm


def _extract_user_input(state: ShoppingState) -> str:
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                return msg.get("content", "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role == "human":
                return getattr(msg, "content", "")
    return ""


def _is_ambiguous_reorder(user_input: str, keywords: list[str]) -> bool:
    text = user_input.strip().lower()
    if keywords:
        return False
    has_reorder_signal = any(token in text for token in ("다시", "또", "재주문", "똑같이", "저번", "지난번"))
    has_ambiguous_ref = any(token in text for token in ("그거", "그것", "저거", "그 상품", "주문한 거", "산 거", "샀던 거"))
    return has_reorder_signal and has_ambiguous_ref


def _degraded_intent_result(state: IntentAgentInput, failure_class: FailureClass, exc: BaseException) -> dict:
    """구조화 출력 실패(품질/영구 기술 오류) 시 즉시 반환하는 축소 응답.
    TRANSIENT_TECHNICAL은 여기로 오지 않는다 — 호출부에서 re-raise해 NODE_RETRY_POLICY가 재시도한다."""
    return {
        "intent": "unclear",
        "keywords": state.get("keywords") or [],
        "exclude_keywords": [],
        "negative_constraints": [],
        "quantity": state.get("quantity"),
        "condition": None,
        "recipe_dish": state.get("recipe_dish"),
        "recipe_people": state.get("recipe_people"),
        "target_platforms": [],
        "override_platform": None,
        "current_option_value": None,
        "address_text": None,
        "needs_clarification": True,
        "clarification_reason": "응답 파싱 오류",
        "confidence": 0.0,
        "immediate_response": "다시 한번 말씀해 주세요.",
        "last_agent": "intent_agent",
        "tool_calls": None,
        "tool_results": None,
        "recommend_from_profile": False,
        "cart_operations": [],
        "degraded_mode": True,
        "failure_stage": "intent_llm",
        "degradation_reason": f"{failure_class.value}:{type(exc).__name__}",
    }


def _format_cart_context(cart_items: Optional[list[dict]]) -> str:
    """장바구니 내용을 프롬프트에 넣어, "서울우유 한 개만"처럼 이미 담긴 품목을
    가리키는 발화를(quantity_change/cart_operations) 담겨있지도 않은 새 품목
    요청(buy)과 혼동하지 않게 한다 — 예전엔 이 정보 자체가 프롬프트에 전혀
    없어(context="" 고정) LLM이 순전히 문장만 보고 추측해야 했다(fl-2026-08-25-001
    Living Test에서 buy로 오분류되는 flakiness로 실측됨)."""
    if not cart_items:
        return "장바구니가 비어있음"
    parts = [
        f"{item.get('product_name', '상품')} {item.get('quantity', 1)}개"
        for item in cart_items
    ]
    return "현재 장바구니: " + ", ".join(parts)


def intent_error_handler(state: ShoppingState, error: NodeError) -> Command:
    """NODE_RETRY_POLICY 소진(TRANSIENT_TECHNICAL) 또는 재시도 대상이 아닌 예외
    (PERMANENT_TECHNICAL) 모두 여기로 온다. classify_failure로 다시 나눠 로그만
    구분하고, 사용자에게는 동일한 안전 응답을 준다."""
    fc = classify_failure(error.error)
    if fc is FailureClass.TRANSIENT_TECHNICAL:
        agent_logger.log_retry_exhausted(node="intent_agent", exception_type=type(error.error).__name__)
    else:
        agent_logger.log_permanent_technical_error(node="intent_agent", exception_type=type(error.error).__name__)
    return Command(
        update=_degraded_intent_result(state, fc, error.error),
        goto="respond",
    )


def intent_agent_node(state: IntentAgentInput, runtime: Runtime | None = None) -> IntentAgentUpdate:
    # runtime은 그래프 실행 시 LangGraph가 자동 주입한다. evals/run_experiment.py
    # 등이 이 노드를 그래프 밖에서 직접 호출할 때는 None이 들어오므로 기본값을 둔다.
    user_input = _extract_user_input(state)
    stage = state.get("stage", "idle")
    pending_action = state.get("pending_action")
    pending_type = pending_action.get("type") if isinstance(pending_action, dict) else "null"

    node_attempt = runtime.execution_info.node_attempt if runtime and runtime.execution_info else 1
    if node_attempt > 1:
        agent_logger.log_retry_attempt_started(node="intent_agent", node_attempt=node_attempt)

    prompt = INTENT_AGENT_PROMPT.format(
        user_input=user_input,
        stage=stage,
        pending_action=pending_type,
        context=_format_cart_context(state.get("cart_items")),
    )

    llm = _get_llm()
    try:
        # OpenAI는 SystemMessage, Claude는 HumanMessage 필수
        # _llm(기본 모델)로 모델명 확인 — structured_llm 래퍼에는 속성 없음
        base_model_name = getattr(_llm, "model_name", "") or getattr(_llm, "model", "") or ""
        if "gpt" in str(base_model_name).lower():
            messages = [SystemMessage(content=prompt)]
        else:
            messages = [HumanMessage(content=prompt)]
        parsed: IntentOutput = llm.invoke(messages)
    except Exception as e:
        fc = classify_failure(e)
        print(f"[intent_agent] structured output error ({fc.value}): {e}")
        if fc is FailureClass.TRANSIENT_TECHNICAL:
            agent_logger.log_transient_failure(node="intent_agent", node_attempt=node_attempt, exception_type=type(e).__name__)
            raise  # NODE_RETRY_POLICY가 노드 재실행, 소진되면 intent_error_handler로 이동
        return _degraded_intent_result(state, fc, e)

    intent = parsed.intent

    # ── reorder 강제 교정: 재구매 신호+상품명 있는데 buy로 잘못 분류된 경우 ──
    kws_for_check = _normalize_keyword_tokens(parsed.keywords or []) or _fallback_search_keywords(user_input)
    if _should_force_reorder(user_input, intent, stage, kws_for_check):
        intent = "reorder"

    # ── buy 강제 교정: idle에서 사줘/구매해 등 트리거 있는데 LLM이 다른 intent ──
    if _should_force_buy_from_freeform(user_input, intent, stage):
        intent = "buy"

    quantity = _parse_quantity(parsed.quantity)
    # product_confirm(수량 미입력) 대기 중 수량 답변 → 재파싱 + intent 교정
    if pending_type == "product_confirm":
        if _looks_like_quantity_reply(user_input):
            direct = _parse_quantity(user_input)
            if direct is not None:
                quantity = direct
                # product_confirm 상태에서 수량을 말하는 건 구매 의사 확정으로 해석
                if not state.get("quantity"):
                    intent = "confirm"

    _search_intents = {"buy", "reorder", "refine", "compare_platforms"}
    if quantity is None and intent not in _search_intents:
        quantity = state.get("quantity")

    # 검색과 무관한 intent는 기존 keywords 유지 (ask/confirm/deny/next 등이 keywords를 덮어쓰면 안 됨)
    if intent in _search_intents:
        keywords = _normalize_keyword_tokens(parsed.keywords or []) or state.get("keywords") or []
        # LLM이 빈 keywords 반환 → 휴리스틱 추출. 단, LLM이 이미
        # needs_clarification=true로 "실제 상품명이 없다"고 판단했으면 원문에서
        # 억지로 뽑지 않는다 — 그러면 "뭐 먹을 거 좀 사야 하는데"의
        # "먹을"/"사야"/"하는데" 같은 조사·어미가 상품명처럼 검색되고, 그 값이
        # state에 남아 이후 턴(next 등)에서 실제 검색에 쓰여 엉뚱한 no_candidates
        # 오류로 이어진다(실측 확인). needs_clarification 케이스는 STOP_WORDS를
        # 계속 추가하는 대신, 애초에 "정말 모호하면 억지로 안 뽑는다"로 일반화한다.
        if not keywords and not parsed.needs_clarification:
            keywords = _fallback_search_keywords(user_input)
    elif intent == "quantity_change":
        # 보통은 지금 선택된 상품을 그대로 가리키지만("3개로 바꿔줘"), 이번 턴에
        # 다른 상품명을 명시했으면(예: "계란은 빼줘") 그 상품을 우선해야 한다 —
        # 무조건 예전 keywords를 우선하면 quantity_change로는 애초에 다른
        # 품목을 절대 가리킬 수 없다(실측 확인, fl-2026-08-18-006).
        keywords = _normalize_keyword_tokens(parsed.keywords or []) or state.get("keywords") or []
    else:
        keywords = state.get("keywords") or _normalize_keyword_tokens(parsed.keywords or [])

    needs_clarification = parsed.needs_clarification
    clarification_reason = parsed.clarification_reason
    confidence = parsed.confidence
    immediate_response = parsed.immediate_response

    # 강제 교정된 reorder: 상품명 있으므로 clarification 불필요, confidence 보정
    if intent == "reorder" and keywords and needs_clarification:
        needs_clarification = False
        clarification_reason = None
        confidence = max(confidence, 0.8)

    # 수량 답변 감지로 quantity가 교정된 경우 clarification 불필요
    if quantity and intent == "confirm" and pending_type == "product_confirm":
        needs_clarification = False
        clarification_reason = None
        confidence = max(confidence, 0.85)

    # 결제 흐름 중 결제수단/배송/환불 질문을 "나는 답을 모른다"는 이유로
    # 방어적으로 되묻지 않는다 — response_agent가 답할 수 있다(WON-19).
    if _should_trust_ask_over_clarification(intent, needs_clarification, clarification_reason, confidence, pending_type):
        needs_clarification = False

    if _is_ambiguous_reorder(user_input, keywords):
        intent = "reorder"
        needs_clarification = True
        clarification_reason = "어떤 상품을 다시 주문할지 알려주세요."
        immediate_response = "어떤 상품을 다시 주문할까요?"

    # "아무거나/상관없어요" 등 dismissive 답변: 되묻는 대신 프로필 기반 추천으로
    # 대체한다 (실제 keywords 채우기는 context_agent가 profile.favorite_foods로).
    recommend_from_profile = _should_force_recommendation_fallback(user_input, intent, stage, keywords)
    if recommend_from_profile:
        needs_clarification = False
        clarification_reason = None
        confidence = max(confidence, 0.8)
        immediate_response = immediate_response or "네, 평소 좋아하시는 걸로 준비해드릴게요."

    # recipe 필드는 buy intent일 때만 갱신, 그 외엔 state 값 유지
    recipe_dish = parsed.recipe_dish if intent == "buy" else (parsed.recipe_dish or state.get("recipe_dish"))
    recipe_people = parsed.recipe_people if intent == "buy" else (parsed.recipe_people or state.get("recipe_people"))

    cart_operations = [op.model_dump() for op in parsed.cart_operations]
    # buy 발화에 서로 다른 상품이 2개 이상 있으면("계란이랑 참기름 사줘") 첫
    # 품목만 이번 턴 keywords/quantity로 좁히고 나머지는 queue_items로 넘긴다.
    multi_buy_split = _split_multi_buy_queue(intent, cart_operations)
    if multi_buy_split:
        keywords = multi_buy_split["keywords"]
        quantity = multi_buy_split["quantity"]

    result = {
        "intent": intent,
        "keywords": keywords,
        "exclude_keywords": parsed.exclude_keywords,
        "negative_constraints": parsed.negative_constraints,
        "quantity": quantity,
        "condition": parsed.condition,
        "recipe_dish": recipe_dish,
        "recipe_people": recipe_people,
        "target_platforms": parsed.target_platforms,
        "override_platform": parsed.override_platform,
        "current_option_value": parsed.current_option_value,
        "address_text": parsed.address_text,
        "needs_clarification": needs_clarification,
        "clarification_reason": clarification_reason,
        "confidence": confidence if confidence > 0 else 0.9,
        "immediate_response": immediate_response,
        "last_agent": "intent_agent",
        "tool_calls": None,
        "tool_results": None,
        "recommend_from_profile": recommend_from_profile,
        "cart_operations": cart_operations,
    }
    if multi_buy_split:
        result["queue_items"] = multi_buy_split["queue_items"]
        result["current_queue_index"] = multi_buy_split["current_queue_index"]
        result["queue_source"] = multi_buy_split["queue_source"]
    # queue_clear_existing은 recommend_from_profile 등과 달리 매 턴 다시 안 쓴다 —
    # "싹 다 비우고 계란만 담아"의 CLEAR_CART 신호는 이 턴(검색 시작)에서
    # cart_operations로 살아있지만, 실제로 담기가 실행되는 Step 0는 보통
    # 2턴 뒤("네" 확인) — 그때는 이번 턴 cart_operations가 이미 사라진 뒤라
    # payment_agent가 소비할 때까지 살아있어야 한다(queue_items와 동일 패턴).
    if _should_clear_existing_cart(intent, cart_operations):
        result["queue_clear_existing"] = True
    agent_logger.log_intent(user_input, stage, pending_action, result)
    return result

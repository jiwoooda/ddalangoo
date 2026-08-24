"""
Satisfaction Check-in — 공용 "만족도 체크인" 부품.

트리거(언제 불릴지)를 모른다 — fallback_orchestrator의 chat 분기가 지금
쓰고 있고, 향후 세션 진입 시 잡담(route_session_start 확장)도 같은 함수를
그대로 재사용할 수 있게, "언제 부를지"와 "부르면 뭘 하는지"를 분리했다.

두 단계로 나뉜다:
  start_satisfaction_checkin  — 아직 만족도를 안 물어본 구매를 골라 되묻는다.
  capture_satisfaction_answer — 그 되물음에 대한 답을 해석해 DB에 기록한다.

두 턴 사이의 연결은 pending_action.payload.satisfaction_check(purchase_history_id,
product_name)로 한다 — product_select가 candidates를 payload에 담아두는 것과
동일한 패턴(새 상태 관리 메커니즘 아님).

톤은 smalltalk_agent(온보딩 딸랑구 캐릭터)와 동일하게 SMALLTALK_CHARACTER를
그대로 재사용한다.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

from configs.llm_config import get_llm
from src.prompts.smalltalk_prompt import SMALLTALK_CHARACTER
from src.prompts.satisfaction_checkin_prompt import SATISFACTION_ASK_PROMPT, SATISFACTION_CAPTURE_PROMPT
from src.tools import db_client
from src.utils.agent_logger import agent_logger
from src.utils.retry import retry_call

_SATISFACTION_SCORE_MAP = {"positive": 5, "neutral": 3, "negative": 1}


class SatisfactionCheckinOutput(BaseModel):
    reply: str = Field(description="자연스러운 대화체 응답 한두 문장.")
    satisfaction: Optional[Literal["positive", "neutral", "negative"]] = Field(
        default=None, description="사용자 답변에서 감지된 만족도. 질문하는 턴이면 항상 null."
    )
    note: Optional[str] = Field(default=None, description="구체적인 코멘트(있으면). 없으면 null.")


_llm = None
_structured_llm = None


def _get_llm():
    global _llm, _structured_llm
    if _llm is None:
        # "context" 모델 슬롯 재사용 — smalltalk_agent와 같은 저비용 모델 티어
        # (핵심 쇼핑 판단이 아니라 가벼운 side conversation이라 새 슬롯 안 늘림).
        _llm = get_llm("context", temperature=0.3, max_tokens=200, retry_owner="application")
        _structured_llm = _llm.with_structured_output(SatisfactionCheckinOutput)
    return _structured_llm


def pick_satisfaction_candidate(user_id: str) -> Optional[dict[str, Any]]:
    """아직 만족도를 안 물어본(satisfaction_score가 비어있는) 가장 최근
    구매를 고른다. 없으면 None — 호출부는 None이면 체크인을 시작하지 않는다."""
    if not user_id:
        return None
    for h in db_client.get_purchase_histories(user_id):  # 이미 최신순
        if h.get("satisfaction_score") is None:
            return h
    return None


def start_satisfaction_checkin(candidate: dict[str, Any]) -> Optional[dict[str, Any]]:
    """만족도를 물어보는 첫 턴. 반환값은 그대로 state["pending_action"]에
    얹으면 되는 dict(payload에 satisfaction_check 포함). LLM 실패 시 None —
    호출부는 이 경우 일반 chat 응답으로 대체해야 한다."""
    prompt = SATISFACTION_ASK_PROMPT.format(
        persona=SMALLTALK_CHARACTER,
        product_name=candidate.get("product_name", "상품"),
        purchased_at=candidate.get("purchased_at", ""),
    )
    try:
        result = retry_call(_get_llm().invoke, [HumanMessage(content=prompt)])
        if not isinstance(result, SatisfactionCheckinOutput):
            raise ValueError("structured output 파싱 실패")
    except Exception as e:
        agent_logger.log(f"[satisfaction_checkin] 질문 생성 실패, 스킵: {e}")
        return None

    return {
        "type": "clarification",
        "message": result.reply,
        "payload": {
            "satisfaction_check": {
                "purchase_history_id": candidate.get("id"),
                "product_name": candidate.get("product_name"),
            }
        },
    }


def capture_satisfaction_answer(user_id: str, pending_check: dict[str, Any], user_text: str) -> str:
    """되물음에 대한 답변 턴. 성공/실패와 무관하게 항상 사용자에게 보여줄
    reply 문자열을 반환한다(기록 실패가 대화 자체를 끊으면 안 됨)."""
    product_name = pending_check.get("product_name", "상품")
    prompt = SATISFACTION_CAPTURE_PROMPT.format(
        persona=SMALLTALK_CHARACTER,
        product_name=product_name,
        user_text=user_text,
    )
    try:
        result = retry_call(_get_llm().invoke, [HumanMessage(content=prompt)])
        if not isinstance(result, SatisfactionCheckinOutput):
            raise ValueError("structured output 파싱 실패")
    except Exception as e:
        agent_logger.log(f"[satisfaction_checkin] 답변 해석 실패: {e}")
        return "네, 알겠어요! 말씀해주셔서 감사해요."

    if result.satisfaction:
        try:
            db_client.update_purchase_satisfaction(
                user_id,
                pending_check.get("purchase_history_id"),
                satisfaction_score=_SATISFACTION_SCORE_MAP.get(result.satisfaction),
                memo=result.note,
            )
            agent_logger.log(
                f"[satisfaction_checkin] 기록 완료 purchase_history_id="
                f"{pending_check.get('purchase_history_id')} satisfaction={result.satisfaction}"
            )
        except Exception as e:
            agent_logger.log(f"[satisfaction_checkin] DB 기록 실패: {e}")

    return result.reply

"""
RoutedSignal — Context Agent 출력의 공통 신호 단위.

context_agent.py(생성) / priority_resolver.py(intent 우선순위 재판정) /
product_agent.py(Stage4 스코어링)가 공유해서 쓴다. 순환 import를 피하려고
agents 모듈이 아니라 여기(state)에 둔다.

timestamp는 LLM이 추측하지 않는다 — source 기준으로 코드가 채운다:
  session_smalltalk  → 이번 요청 시각
  purchase_history   → 근거가 된 구매이력의 purchased_at
  general_context    → 프로필 캐시의 computed_at
"""
from typing import Literal, Optional
from pydantic import BaseModel

SignalSource = Literal["general_context", "purchase_history", "session_smalltalk"]
DecisionRole = Literal["retrieval", "explicit_exclusion", "soft_preference"]


class RoutedSignal(BaseModel):
    signal_id: str
    value: str
    source: SignalSource
    evidence: str
    decision_role: DecisionRole
    timestamp: Optional[str] = None  # ISO 8601 문자열

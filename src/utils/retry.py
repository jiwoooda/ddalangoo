"""
LLM 예외를 3가지로 분류하고, 그래프 노드/LLM 호출 재시도 정책을 제공한다.

- TRANSIENT_TECHNICAL: 연결 오류·타임아웃·429·5xx → 재시도하면 회복될 수 있음
- PERMANENT_TECHNICAL: 401/403/400 등 인증·설정 오류 → 재시도해도 회복 안 됨
- QUALITY_VALIDATION: 구조화 출력 검증 실패(pydantic.ValidationError, 수동 ValueError 등)
  → 재시도해도 같은 실패가 반복될 가능성이 높음, 즉시 축소 응답으로 처리

anthropic와 openai SDK는 공통 부모가 없는 별개의 예외 계층이므로 둘 다 명시적으로 나열한다.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, TypeVar

import anthropic
import openai
from langgraph.types import RetryPolicy


class FailureClass(Enum):
    TRANSIENT_TECHNICAL = "transient_technical"
    PERMANENT_TECHNICAL = "permanent_technical"
    QUALITY_VALIDATION = "quality_validation"


_TRANSIENT_TYPES = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)
_PERMANENT_TYPES = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.BadRequestError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.BadRequestError,
)


def classify_failure(exc: BaseException) -> FailureClass:
    """anthropic/openai는 공통 부모가 없는 별개 SDK 예외 계층이므로 둘 다 명시한다."""
    if isinstance(exc, _TRANSIENT_TYPES):
        return FailureClass.TRANSIENT_TECHNICAL
    if isinstance(exc, _PERMANENT_TYPES):
        return FailureClass.PERMANENT_TECHNICAL

    status_code = getattr(exc, "status_code", None)
    if status_code == 408 or status_code == 429 or (isinstance(status_code, int) and status_code >= 500):
        return FailureClass.TRANSIENT_TECHNICAL
    if isinstance(status_code, int) and status_code in (400, 401, 403):
        return FailureClass.PERMANENT_TECHNICAL

    return FailureClass.QUALITY_VALIDATION


def is_transient_llm_error(exc: BaseException) -> bool:
    return classify_failure(exc) is FailureClass.TRANSIENT_TECHNICAL


# Node 전체를 재시도하는 그래프 노드(intent_agent, smalltalk_agent)에 부착.
NODE_RETRY_POLICY = RetryPolicy(
    retry_on=is_transient_llm_error,
    max_attempts=3,
    initial_interval=0.5,
    backoff_factor=2.0,
    jitter=True,
)


_T = TypeVar("_T")


def retry_call(
    fn: Callable[..., _T],
    *args: Any,
    max_attempts: int = 3,
    initial_interval: float = 0.5,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> _T:
    """호출 단위(call-level) 재시도 헬퍼.

    검색·프로필 저장 등 다른 부수효과가 섞여 있어 노드 전체를 재시도할 수 없는
    노드(context_agent, product_agent, response_agent, recipe_agent) 안에서, LLM
    호출 한 줄만 감싸는 용도. TRANSIENT_TECHNICAL만 재시도하고, 그 외(PERMANENT_TECHNICAL,
    QUALITY_VALIDATION)는 즉시 원래 예외를 다시 던져 호출부의 기존 except 블록이 폴백을
    반환하게 한다.
    """
    interval = initial_interval
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if classify_failure(e) is not FailureClass.TRANSIENT_TECHNICAL:
                raise
            if attempt >= max_attempts:
                raise
            time.sleep(interval)
            interval *= backoff_factor
    raise last_exc  # pragma: no cover - 위 루프에서 항상 return/raise

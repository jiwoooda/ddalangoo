"""Typed recovery contracts with no runtime dependency on the graph state."""
from __future__ import annotations

from typing import Any, Final, Literal, Optional, TypeAlias, TypedDict

from src.state.common_types import Intent, Stage


FailureKind: TypeAlias = Literal[
    "INTERPRETATION_FAILED",
    "UNHANDLED_TRANSITION",
    "MISSING_CONTEXT",
    "EXECUTION_FAILED",
    "POSTCONDITION_FAILED",
    "NO_PROGRESS",
    "LOOP_DETECTED",
    "RISK_BLOCKED",
]
Retryability: TypeAlias = Literal["none", "safe_once", "bounded", "human_confirm"]
SideEffectRisk: TypeAlias = Literal["none", "read", "write", "high"]
ProgressStatus: TypeAlias = Literal[
    "PROGRESSED",
    "WAITING_USER",
    "ANSWERED",
    "COMPLETED",
    "SAFE_BLOCKED",
    "NO_PROGRESS",
    "LOOP_DETECTED",
]
RecoveryStatus: TypeAlias = Literal["idle", "recovering", "waiting_user", "safe_stopped"]
ProgressSignature: TypeAlias = dict[str, Any]

# Policy values approved for the first recovery rollout. They are contracts only
# here; a later recovery node enforces them without changing their meaning.
MAX_AUTOMATIC_RECOVERY_ATTEMPTS_PER_FINGERPRINT: Final[int] = 1
FREE_FORM_RECOVERY_EXCLUDED_STAGES: Final[frozenset[str]] = frozenset(
    {"payment_processing", "payment_password_required"}
)


class FailureEvent(TypedDict):
    """A deterministic failure observation; never contains user message contents."""

    kind: FailureKind
    source: str
    code: str
    stage: "Stage"
    pending_type: Optional[str]
    intent: Optional["Intent"]
    retryability: Retryability
    side_effect_risk: SideEffectRisk
    context_keys: list[str]


def keep_first_failure(
    active_failure: FailureEvent | None,
    candidate: FailureEvent,
) -> FailureEvent:
    """Keep one root cause per turn; later symptoms cannot consume another attempt."""
    return active_failure if active_failure is not None else candidate

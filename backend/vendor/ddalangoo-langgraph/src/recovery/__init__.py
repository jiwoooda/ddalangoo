"""Recovery contracts shared by failure producers and recovery consumers."""

from .types import (
    FREE_FORM_RECOVERY_EXCLUDED_STAGES,
    MAX_AUTOMATIC_RECOVERY_ATTEMPTS_PER_FINGERPRINT,
    FailureEvent,
    FailureKind,
    ProgressSignature,
    ProgressStatus,
    RecoveryStatus,
)

__all__ = [
    "FailureEvent",
    "FailureKind",
    "FREE_FORM_RECOVERY_EXCLUDED_STAGES",
    "MAX_AUTOMATIC_RECOVERY_ATTEMPTS_PER_FINGERPRINT",
    "ProgressSignature",
    "ProgressStatus",
    "RecoveryStatus",
]

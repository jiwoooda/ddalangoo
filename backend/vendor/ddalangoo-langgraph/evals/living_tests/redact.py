"""PII sanitize 게이트 — failure_log.jsonl/케이스 정의에 뭔가 쓰기 전에는
항상 이 모듈을 통과시킨다.

지금 당장(VIVID mock persona 단계)은 급하지 않지만, production/수동 로그가
들어오기 시작하면 이름/주소/건강정보/결제정보가 raw_input/raw_context/
observed_actual에 섞여 들어올 수 있다. 나중에 추가하면 이미 git에 쌓인
파일들을 소급 처리해야 하므로 Phase 1부터 게이트를 걸어둔다.

원본이 필요하면 git에 올라가지 않는 안전한 위치(예: gitignore된 logs/)를
가리키는 source_ref만 남기고, PII 원본 자체는 여기서 절대 커밋되지 않는다.
"""
from __future__ import annotations

import re
from typing import Any

# 필드명 자체가 PII를 담고 있다고 알려진 키들 — dict를 재귀적으로 순회하며
# 이 이름과 일치하는 키의 값은 무조건 마스킹한다(값의 내용을 파싱하지 않음).
PII_FIELD_BLOCKLIST = {
    "preferred_name", "name", "user_name", "address_text", "address",
    "default_address", "health_notes", "payment_method", "card_number",
    "phone", "phone_number", "email", "account_number", "resident_number",
}

# 필드명을 모르는 자유 텍스트(observed_actual/rationale 등)에 대한 정규식 스캔.
_PHONE_RE = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RESIDENT_NUM_RE = re.compile(r"\d{6}-\d{7}")
_CARD_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{4}")

_TEXT_PATTERNS = [
    (_PHONE_RE, "[REDACTED_PHONE]"),
    (_EMAIL_RE, "[REDACTED_EMAIL]"),
    (_RESIDENT_NUM_RE, "[REDACTED_RESIDENT_NUM]"),
    (_CARD_RE, "[REDACTED_CARD]"),
]


def redact_text(value: str) -> str:
    for pattern, mask in _TEXT_PATTERNS:
        value = pattern.sub(mask, value)
    return value


def redact_value(key: str, value: Any) -> Any:
    if key.lower() in PII_FIELD_BLOCKLIST:
        return f"[REDACTED:{key}]"
    return redact(value)


def redact(value: Any) -> Any:
    """dict/list/str을 재귀적으로 순회하며 PII를 마스킹한 새 값을 반환한다.
    원본은 건드리지 않는다(순수 함수)."""
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_failure_record(record: dict[str, Any]) -> dict[str, Any]:
    """failure_log.jsonl에 쓰기 직전 호출. input/context_summary/observed_actual만
    정제하고 나머지 메타필드(failure_id/status 등)는 건드리지 않는다."""
    record = dict(record)
    for field in ("input", "context_summary", "observed_actual", "notes"):
        if field in record and record[field] is not None:
            record[field] = redact(record[field])
    return record

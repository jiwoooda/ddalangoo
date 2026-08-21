"""Living Test Set 저장소 — 스키마 검증 + append/read.

책임 분리 (AGENT_IMPROVEMENT_PROTOCOL.md 참고):
  Failure = 무엇이 실패했고, 왜 실패했는가(root_cause 포함) — failure_log.jsonl
  Test    = 앞으로 어떤 Behavior를 보장해야 하는가 — unit/integration/e2e 밑 *.jsonl, 생성 후 불변
  Run     = 이번 실행이 그 Behavior를 통과했는가 — runs/**/*.json (이 모듈이 직접 쓰지 않음, runner.py 몫)

  케이스 정의 파일(Test)은 append만 하고 절대 rewrite하지 않는다. 실행/판정 이력은
  case_events.jsonl(append-only)에만 쌓는다 — verdict 이력 자체는 runs/**/*.json을
  case_id로 스캔해서 구하고, 별도 verdicts.jsonl은 두지 않는다(runs/와의 중복 제거).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Literal

BASE_DIR = Path(__file__).resolve().parent

# scope→target 허용값. unit은 target별로 파일이 따로 있고(agent 1:1),
# integration/e2e는 케이스 수가 적어 파일 하나에 target 필드로만 구분한다.
SCOPES: dict[str, list[str]] = {
    "unit": ["intent_agent", "context_agent", "product_agent", "response_agent", "smalltalk_agent", "reorder_agent", "payment_agent", "respond"],
    "integration": ["routing", "handoff", "tool_flow", "state_transition", "context_preservation"],
    "e2e": ["workflows"],
}

# root_cause.type 허용값 — 10종 고정, 더 세분화하지 않는다.
# tool vs code_logic: tool 경계 자체(선택/입력/출력/실행)가 문제면 tool,
#   tool은 정상 값을 돌려줬고 그걸 갖고 우리 코드가 내린 판단이 문제면 code_logic.
# model: prompt/context/tool/state/orchestration을 다 확인하고 통제된 입력으로
#   재현까지 됐을 때만 — "원인을 못 찾아서 model"은 금지, 그럴 땐 unknown 유지.
ROOT_CAUSE_TYPES = (
    "unknown", "prompt", "model", "orchestration", "context_memory",
    "tool", "state", "data", "code_logic", "response",
)

FAILURE_STATUSES = ("unassigned", "traced", "triaged", "dismissed")

# Failure.reproduction.status 허용값. 판정의 유일한 Source of Truth — Reproduction
# Run(runs/reproduction/*.json)에는 판정 필드가 없고 실행 사실(observed)만 남는다.
REPRODUCTION_STATUSES = ("pending", "reproduced", "not_reproduced", "blocked")

# dashboard.py::AGENT_PROMPT_FILES와 같은 내용을 유지한다 — dashboard.py는
# streamlit을 top-level import하므로 여기서 그걸 그대로 import하면 triage.py
# 같은 가벼운 CLI에도 streamlit 의존이 강제된다. 두 곳 다 손으로 맞춰 관리.
# 딸랑구 프롬프트는 실행 중 동적으로 조합되지 않는 정적 템플릿이라(.format()으로
# 값만 채움) prompt_hash는 필수 필드가 아니라 필요할 때 쓰는 유틸로만 남긴다.
AGENT_PROMPT_FILES: dict[str, list[str]] = {
    "context": ["src/prompts/context_prompt.py"],
    "product": ["src/prompts/scoring_prompt.py", "src/prompts/product_prompt.py"],
    "response": ["src/prompts/response_prompt.py"],
    "intent": ["src/prompts/intent_prompt.py"],
    "recipe": ["src/prompts/recipe_prompt.py"],
    "smalltalk": ["src/prompts/smalltalk_prompt.py"],
    "reorder": [],
}

FAILURE_LOG_PATH = BASE_DIR / "failure_log.jsonl"
CASE_EVENTS_PATH = BASE_DIR / "case_events.jsonl"

REQUIRED_CASE_FIELDS = ("case_id", "scope", "target", "input", "context", "expected_behavior", "rationale")
REQUIRED_FAILURE_FIELDS = ("failure_id", "discovered_at", "discovered_by", "source", "observed_actual", "status")


class SchemaError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _git_short_hash() -> str:
    """local_runner.py::_git_short_hash()와 동일한 로직의 독립 사본 — store.py는
    living_tests/ 바깥 모듈에 의존하지 않는 최하위 레이어로 유지한다."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def prompt_hash(path: str | Path) -> str | None:
    """sha256(파일 bytes)[:16] — 필수 필드는 아니고 필요할 때 쓰는 유틸."""
    import hashlib
    p = Path(path)
    if not p.is_absolute():
        p = BASE_DIR.parent.parent / path
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


# ── 순수 JSONL 유틸 ──────────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Test 정의 (불변) ─────────────────────────────────────────────

def case_path(scope: str, target: str) -> Path:
    if scope not in SCOPES:
        raise SchemaError(f"알 수 없는 scope: {scope!r} (허용: {list(SCOPES)})")
    if target not in SCOPES[scope]:
        raise SchemaError(f"'{scope}' scope에 '{target}'는 없음 (허용: {SCOPES[scope]})")
    if scope == "unit":
        return BASE_DIR / "unit" / f"{target}.jsonl"
    if scope == "integration":
        return BASE_DIR / "integration" / "cases.jsonl"
    return BASE_DIR / "e2e" / "workflows.jsonl"


def _all_case_paths() -> list[Path]:
    paths = [BASE_DIR / "unit" / f"{t}.jsonl" for t in SCOPES["unit"]]
    paths.append(BASE_DIR / "integration" / "cases.jsonl")
    paths.append(BASE_DIR / "e2e" / "workflows.jsonl")
    return paths


def next_case_id(target: str) -> str:
    """{target}-{date}-{seq}. integration/e2e는 파일을 공유하지만 target별로
    번호를 따로 센다(케이스 id 자체는 무슨 target인지 이름에서 바로 보이게)."""
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    existing = read_all_cases()
    seq = 1 + sum(1 for c in existing if c["case_id"].startswith(f"{target}-{date_str}-"))
    return f"{target}-{date_str}-{seq:03d}"


def validate_case(case: dict[str, Any]) -> None:
    missing = [f for f in REQUIRED_CASE_FIELDS if f not in case or case[f] in (None, "")]
    if missing:
        raise SchemaError(f"케이스에 필수 필드 누락: {missing}")
    if not isinstance(case.get("rationale"), str) or len(case["rationale"].strip()) < 5:
        raise SchemaError("rationale은 5자 이상의 설명이어야 함 — 왜 expected가 맞는지 없이는 나중에 재검토 불가")


def append_case(scope: str, target: str, case: dict[str, Any]) -> str:
    """케이스를 1회 기록한다. 이후 같은 case_id로 다시 쓰지 않는다(불변 원칙) —
    수정이 필요하면 새 case_id로 별도 기록한다."""
    case = dict(case)
    case.setdefault("case_id", next_case_id(target))
    case.setdefault("scope", scope)
    case.setdefault("target", target)
    case.setdefault("source_failure", None)
    case.setdefault("expected_assertions", [])
    case.setdefault("fixture_id", None)
    case.setdefault("discovered_at", _now_iso())
    case.setdefault("tags", [])
    validate_case(case)
    path = case_path(scope, target)
    existing_ids = {c["case_id"] for c in _read_jsonl(path)}
    if case["case_id"] in existing_ids:
        raise SchemaError(f"case_id 중복: {case['case_id']} (living test는 불변 — 새 id로 기록할 것)")
    _append_jsonl(path, case)
    return case["case_id"]


def read_cases(scope: str, target: str) -> list[dict[str, Any]]:
    path = case_path(scope, target)
    return [c for c in _read_jsonl(path) if c.get("target") == target]


def read_all_cases() -> list[dict[str, Any]]:
    rows = []
    for path in _all_case_paths():
        rows.extend(_read_jsonl(path))
    return rows


def get_case(case_id: str) -> dict[str, Any] | None:
    for c in read_all_cases():
        if c["case_id"] == case_id:
            return c
    return None


# ── Stage A: failure_log (Failure = 무엇이 실패했고 왜 실패했는가) ──────

def next_failure_id() -> str:
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    existing = _read_jsonl(FAILURE_LOG_PATH)
    seq = 1 + sum(1 for f in existing if f["failure_id"].startswith(f"fl-{date_str}-"))
    return f"fl-{date_str}-{seq:03d}"


def validate_failure(failure: dict[str, Any]) -> None:
    missing = [f for f in REQUIRED_FAILURE_FIELDS if f not in failure or failure[f] in (None, "")]
    if missing:
        raise SchemaError(f"failure_log 항목에 필수 필드 누락: {missing}")
    if failure["status"] not in FAILURE_STATUSES:
        raise SchemaError(f"status는 {FAILURE_STATUSES} 중 하나여야 함")


def append_failure(failure: dict[str, Any]) -> str:
    """root_cause는 항상 unknown으로, reproduction은 항상 pending으로 시작한다 —
    Reproduce/Trace/Diagnose 전에 재현 여부나 원인을 단정하지 않는다는 게 이
    시스템의 핵심 원칙이라, 여기서 다른 값을 받지 않는다."""
    failure = dict(failure)
    failure.setdefault("failure_id", next_failure_id())
    failure.setdefault("discovered_at", _now_iso())
    failure.setdefault("status", "unassigned")
    failure.setdefault("input", {})
    failure.setdefault("context_summary", None)
    failure["reproduction"] = {"status": "pending", "git_sha": None, "run_ref": None, "reason": None}
    failure.setdefault("trace_notes", "")
    failure["root_cause"] = {"type": "unknown", "component": None, "reason": None}
    failure.setdefault("triaged_to_case_ids", [])
    failure.setdefault("notes", None)
    validate_failure(failure)
    _append_jsonl(FAILURE_LOG_PATH, failure)
    return failure["failure_id"]


def read_failures() -> list[dict[str, Any]]:
    return _read_jsonl(FAILURE_LOG_PATH)


def get_failure(failure_id: str) -> dict[str, Any] | None:
    for f in read_failures():
        if f["failure_id"] == failure_id:
            return f
    return None


def _update_failure(failure_id: str, **updates: Any) -> dict[str, Any]:
    """failure_log.jsonl은 파일이 작아서(수십~수백 줄) read-all/rewrite-all로
    갱신한다 — Test 정의 파일과 달리 이 Inbox는 처리 상태를 추적하는 게
    목적이라 rewrite가 원칙 위반이 아니다(불변이어야 하는 건 Stage B뿐)."""
    rows = read_failures()
    found = None
    for row in rows:
        if row["failure_id"] == failure_id:
            row.update(updates)
            found = row
            break
    if found is None:
        raise SchemaError(f"failure_id를 찾을 수 없음: {failure_id}")
    _rewrite_jsonl(FAILURE_LOG_PATH, rows)
    return found


def set_reproduction(
    failure_id: str, status: str, *,
    run_ref: str | None = None, reason: str | None = None, git_sha: str | None = None,
) -> None:
    """REPRODUCE/VALIDATE 판정을 기록하는 유일한 지점 — 재현 여부의 Source of
    Truth는 이 필드뿐이다. Reproduction Run(runs/reproduction/*.json)은 실행
    사실(observed)만 담고 판정 필드가 없으므로, 사람이 그 observed와 Failure의
    observed_actual을 비교해서 이 함수로 직접 판정을 남긴다."""
    if status not in REPRODUCTION_STATUSES:
        raise SchemaError(f"reproduction.status는 {REPRODUCTION_STATUSES} 중 하나여야 함")
    if get_failure(failure_id) is None:
        raise SchemaError(f"failure_id를 찾을 수 없음: {failure_id}")
    reproduction = {
        "status": status,
        "git_sha": git_sha or _git_short_hash(),
        "run_ref": run_ref,
        "reason": reason,
    }
    _update_failure(failure_id, reproduction=reproduction)


def set_trace_notes(failure_id: str, notes: str) -> None:
    """TRACE 단계 결과를 기록. status가 unassigned면 traced로 올린다.

    reproduction.status가 'reproduced'가 아닌 Failure는 TRACE 대상이 아니다 —
    재현 안 된 문제를 추적/진단하면 안 된다는 원칙을 여기서 강제한다. 이게
    not_reproduced/blocked가 절대 traced로 잘못 표시되지 않는 핵심 가드다."""
    failure = get_failure(failure_id)
    if failure is None:
        raise SchemaError(f"failure_id를 찾을 수 없음: {failure_id}")
    reproduction_status = (failure.get("reproduction") or {}).get("status")
    if reproduction_status != "reproduced":
        raise SchemaError(
            f"reproduction.status가 'reproduced'가 아닌 Failure는 TRACE할 수 없음 "
            f"(현재: {reproduction_status!r}). 먼저 REPRODUCE/VALIDATE부터 진행할 것"
        )
    updates: dict[str, Any] = {"trace_notes": notes}
    if failure["status"] == "unassigned":
        updates["status"] = "traced"
    _update_failure(failure_id, **updates)


def set_root_cause(failure_id: str, type: str, component: str | None, reason: str) -> None:
    """DIAGNOSE 결과 확정. model 타입은 남용 가드가 있다 —
    AGENT_IMPROVEMENT_PROTOCOL.md의 규칙(다른 경로를 다 확인하고 재현까지
    됐을 때만 model)은 코드로 강제하지 않고 사람 판단에 맡긴다(과도한 제약
    방지) — 대신 store 레벨에서는 타입 값 자체만 검증한다."""
    if type not in ROOT_CAUSE_TYPES:
        raise SchemaError(f"root_cause.type은 {ROOT_CAUSE_TYPES} 중 하나여야 함")
    failure = get_failure(failure_id)
    if failure is None:
        raise SchemaError(f"failure_id를 찾을 수 없음: {failure_id}")
    _update_failure(failure_id, root_cause={"type": type, "component": component, "reason": reason})


def mark_triaged(failure_id: str, case_ids: list[str]) -> None:
    failure = get_failure(failure_id)
    if failure is None:
        raise SchemaError(f"failure_id를 찾을 수 없음: {failure_id}")
    merged = list(dict.fromkeys(failure.get("triaged_to_case_ids", []) + case_ids))
    _update_failure(failure_id, status="triaged", triaged_to_case_ids=merged)


def dismiss_failure(failure_id: str, reason: str) -> None:
    _update_failure(failure_id, status="dismissed", notes=reason)


# ── case_events (append-only — 케이스의 수정/상태 이력, Test 정의는 안 건드림) ──

def append_case_event(case_id: str, event: str, **fields: Any) -> None:
    if get_case(case_id) is None:
        raise SchemaError(f"case_id를 찾을 수 없음: {case_id}")
    row = {"case_id": case_id, "event": event, "at": _now_iso(), **fields}
    _append_jsonl(CASE_EVENTS_PATH, row)


def record_fix(
    case_id: str, *, by: str, fix_component: str, fix_summary: str,
    git_sha: str | None = None, regression_result: str = "pending",
    status: str = "fixed",
) -> None:
    append_case_event(
        case_id, "fix_recorded", by=by, status=status,
        fix_component=fix_component, fix_summary=fix_summary,
        git_sha=git_sha or _git_short_hash(), regression_result=regression_result,
    )


def case_status(case_id: str) -> str:
    """case_events.jsonl에서 이 case_id의 가장 최근 status 값을 찾는다.
    없으면 'open'이 기본값."""
    latest_status = "open"
    for row in _read_jsonl(CASE_EVENTS_PATH):
        if row.get("case_id") == case_id and row.get("status"):
            latest_status = row["status"]
    return latest_status


def case_events_for(case_id: str) -> list[dict[str, Any]]:
    return [r for r in _read_jsonl(CASE_EVENTS_PATH) if r.get("case_id") == case_id]

"""Stage A 캡처 CLI — 실패를 발견한 순간 최소한의 마찰로 failure_log.jsonl에
기록한다. root_cause는 항상 unknown으로 시작한다(store.append_failure가 강제) —
TRACE/DIAGNOSE 전에 원인을 단정하지 않는다.

사용법:
  python -m evals.living_tests.log_failure --source manual_repl --by human:jiow2003 \
      --input '{"user": "우유 하나만 남겨줘"}' --context-summary "cart contains milk x3" \
      --observed "장바구니 우유 수량이 3 그대로임"

  # agent_logger가 만든 .jsonl에서 특정 턴을 뽑아 input/context_summary를 채움
  python -m evals.living_tests.log_failure --source manual_repl --by human:jiow2003 \
      --from-log logs/session_20260818.jsonl --turn 4 \
      --observed "reorder 대신 product_agent가 엉뚱한 검색을 함"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.living_tests import store
from evals.living_tests.redact import redact_failure_record

_SOURCES = ("vivid_trial", "manual_repl", "e2e_test_failure", "agent_log", "production")


def _extract_from_log(log_path: str, turn: int) -> tuple[dict[str, Any], str | None, str | None]:
    """agent_logger가 쓴 .jsonl에서 특정 turn의 이벤트들을 모아
    (input, context_summary 힌트, observed_actual 힌트)로 만든다.
    scripts/check_fallback_rate.py와 동일하게 그 .jsonl을 읽기만 한다 —
    agent_logger.py 자체는 건드리지 않는다."""
    events: list[dict[str, Any]] = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("turn") == turn:
                events.append(row)

    user_input = None
    context_parts: list[str] = []
    observed_hint = None

    for row in events:
        event = row.get("event")
        if event == "turn_start":
            user_input = row.get("user_input")
        elif event == "intent_agent":
            context_parts.append(f"intent={row.get('intent')} keywords={row.get('keywords')}")
        elif event == "router":
            context_parts.append(f"router {row.get('from')}->{row.get('to')}")
        elif event == "respond":
            observed_hint = row.get("message")

    input_data = {"user": user_input} if user_input else {}
    context_summary = "; ".join(context_parts) if context_parts else None
    return input_data, context_summary, observed_hint


def main() -> None:
    parser = argparse.ArgumentParser(description="실패를 failure_log.jsonl(Stage A)에 캡처")
    parser.add_argument("--source", choices=_SOURCES, required=True)
    parser.add_argument("--by", dest="discovered_by", required=True, help="예: human:jiow2003, vivid, e2e_test")
    parser.add_argument("--ref", dest="source_ref", default=None, help="trace를 다시 볼 수 있는 경로")
    parser.add_argument("--observed", dest="observed_actual", default=None, help="무엇이 잘못됐는지(자유 텍스트)")
    parser.add_argument("--input", dest="input_json", default=None, help='JSON, 예: \'{"user": "우유 하나만 남겨줘"}\'')
    parser.add_argument("--context-summary", dest="context_summary", default=None,
                         help="재현에 필요한 최소 맥락 한 줄(전체 대화 복제 아님)")
    parser.add_argument("--from-log", dest="from_log", default=None, help="agent_logger .jsonl 경로")
    parser.add_argument("--turn", type=int, default=None, help="--from-log와 함께 사용, 턴 번호")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    input_data: dict[str, Any] = json.loads(args.input_json) if args.input_json else {}
    context_summary = args.context_summary
    observed_hint = None

    if args.from_log:
        if args.turn is None:
            raise SystemExit("--from-log를 쓰려면 --turn도 필요합니다.")
        if not Path(args.from_log).exists():
            raise SystemExit(f"로그 파일을 찾을 수 없습니다: {args.from_log}")
        log_input, log_context, observed_hint = _extract_from_log(args.from_log, args.turn)
        input_data = input_data or log_input
        context_summary = context_summary or log_context

    observed_actual = args.observed_actual or observed_hint
    if not observed_actual:
        observed_actual = input("무엇이 잘못됐나요? (observed_actual): ").strip()
    if not observed_actual:
        raise SystemExit("observed_actual 없이는 기록할 수 없습니다.")

    if not input_data:
        raw = input("input (재현에 필요한 최소 사용자 입력, 예: 우유 하나만 남겨줘, 생략 가능): ").strip()
        if raw:
            input_data = {"user": raw}

    record = {
        "source": args.source,
        "discovered_by": args.discovered_by,
        "source_ref": args.source_ref or args.from_log,
        "input": input_data,
        "context_summary": context_summary,
        "observed_actual": observed_actual,
        "notes": args.notes,
    }
    record = redact_failure_record(record)
    failure_id = store.append_failure(record)
    print(f"기록됨: {failure_id}  (status=unassigned, root_cause=unknown)")
    print("다음: TRACE 결과를 확인한 뒤 python -m evals.living_tests.triage --failure", failure_id, "...")


if __name__ == "__main__":
    main()

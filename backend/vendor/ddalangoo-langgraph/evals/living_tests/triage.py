"""TRACE 결과를 바탕으로 root_cause를 확정(Failure에 기록)하고, 그 원인을
재현하는 최소 Test 케이스 하나를 만든다(Stage A → B).

root_cause는 Failure의 소유다 — Test는 source_failure로 그 Failure를
가리킬 뿐 root_cause를 복제하지 않는다(Failure=무엇이·왜, Test=앞으로
보장할 것, Run=이번에 통과했는가).

실패 하나가 정말 여러 Test로 쪼개져야 하면(원인이 실제로 있는 지점 + 재발
방지가 필요한 다른 지점) 이 커맨드를 같은 --failure에 대해 여러 번 실행한다
— 대부분은 1번, 많아야 2번이면 충분하다(Trace가 지나간 모든 지점에
자동으로 Test를 만들지 않는다).

사용법:
  python -m evals.living_tests.triage --failure fl-2026-08-18-005 \
      --trace-notes "intent_agent 정상, router 정상, product_agent 랭킹에서 처음 어긋남" \
      --root-cause-type code_logic \
      --root-cause-component "src/agents/product_agent.py::_rank_with_metadata" \
      --root-cause-reason "브랜드 일치가 랭킹의 하드 조건이 아님" \
      --scope unit --target product_agent \
      --expected-behavior "..." --rationale "..."
"""
from __future__ import annotations

import argparse
import json

from evals.living_tests import store

_ROOT_CAUSE_GUIDANCE = {
    "tool": "tool 경계 자체(선택/입력/출력/실행)의 문제일 때만. tool이 정상 값을 돌려줬다면 code_logic.",
    "code_logic": "tool/context가 정상 값을 준 '다음' 우리 코드의 판단(랭킹/필터/정책)이 문제일 때.",
    "model": "prompt/context/tool/state/orchestration을 다 확인했고 통제된 입력으로 재현까지 됐을 때만. "
             "원인을 못 찾았으면 model이 아니라 unknown으로 남길 것.",
}


def _ask(prompt: str, required: bool = True) -> str:
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("  (필수 입력입니다)")


def _ask_list(prompt: str) -> list[str]:
    raw = input(prompt).strip()
    return [v.strip() for v in raw.split(",") if v.strip()] if raw else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Failure의 root_cause를 확정하고 최소 Test 케이스를 생성")
    parser.add_argument("--failure", required=True, help="failure_id")
    parser.add_argument("--trace-notes", default=None, help="TRACE 단계 결과(비워두면 Failure에 이미 있는 값 사용/대화식 입력)")
    parser.add_argument("--root-cause-type", required=True, choices=store.ROOT_CAUSE_TYPES)
    parser.add_argument("--root-cause-component", default=None)
    parser.add_argument("--root-cause-reason", required=True)
    parser.add_argument("--scope", required=True, choices=list(store.SCOPES))
    parser.add_argument("--target", required=True, help="scope 안의 대상(예: product_agent / routing / workflows)")
    parser.add_argument("--expected-behavior", default=None)
    parser.add_argument("--rationale", default=None)
    parser.add_argument("--assertion", action="append", default=[],
                         help='JSON, 반복 가능. 예: \'{"type":"field_equals","path":"selected_product.brand","value":"서울우유"}\'')
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--fixture-id", default=None)
    parser.add_argument("--input", dest="input_json", default=None, help="JSON, 생략하면 failure_log의 input 사용")
    parser.add_argument("--context", dest="context_json", default=None, help="JSON, 생략하면 빈 dict")
    args = parser.parse_args()

    failure = store.get_failure(args.failure)
    if failure is None:
        raise SystemExit(f"failure_id를 찾을 수 없습니다: {args.failure}")

    trace_notes = args.trace_notes or failure.get("trace_notes") or _ask(
        "trace_notes (어디까지 정상이고 어디서 처음 깨졌는지): "
    )
    store.set_trace_notes(args.failure, trace_notes)

    guidance = _ROOT_CAUSE_GUIDANCE.get(args.root_cause_type)
    if guidance:
        print(f"[참고] root_cause.type={args.root_cause_type}: {guidance}")
    store.set_root_cause(
        args.failure, type=args.root_cause_type,
        component=args.root_cause_component, reason=args.root_cause_reason,
    )

    expected_behavior = args.expected_behavior or _ask("expected_behavior (기대 동작): ")
    rationale = args.rationale or _ask("rationale (왜 expected가 맞는지): ")
    tags = args.tag or _ask_list("tags (콤마로, 생략 가능): ")
    assertions = [json.loads(a) for a in args.assertion]
    input_data = json.loads(args.input_json) if args.input_json else (failure.get("input") or {})
    context_data = json.loads(args.context_json) if args.context_json else {}

    case = {
        "source_failure": failure["failure_id"],
        "input": input_data,
        "context": context_data,
        "expected_behavior": expected_behavior,
        "expected_assertions": assertions,
        "rationale": rationale,
        "fixture_id": args.fixture_id,
        "discovered_at": failure["discovered_at"],
        "tags": tags,
    }
    case_id = store.append_case(args.scope, args.target, case)
    store.mark_triaged(failure["failure_id"], [case_id])
    print(f"케이스 생성됨: {case_id}  (scope={args.scope}, target={args.target})")
    print(f"failure {failure['failure_id']} → status=triaged, triaged_to_case_ids에 연결됨")


if __name__ == "__main__":
    main()

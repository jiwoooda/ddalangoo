"""
Intent Agent - quantity_confirm 구간 프롬프트 실험 (실시간 로그)

실행: python tests/test_intent_quantity.py
      python tests/test_intent_quantity.py --verbose   # 프롬프트 전문 포함
pytest: python -m pytest tests/test_intent_quantity.py -v -s
"""
import json
import os
import sys
import argparse
from typing import Any, Union

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from src.agents.intent_agent import IntentOutput, _parse_quantity
from src.prompts.intent_prompt import INTENT_AGENT_PROMPT
from src.state.schema import get_default_shopping_state

# ── 실험 케이스 ───────────────────────────────────────────────────────────────
# (user_input, 예상 intent, 예상 quantity, 설명)
QUANTITY_CASES = [
    ("한 개",                   "confirm", 1,    "순우리말 1"),
    ("하나만요",                 "confirm", 1,    "하나 + 요"),
    ("두 개",                   "confirm", 2,    "순우리말 2"),
    ("둘이요",                   "confirm", 2,    "둘 + 이요"),
    ("세 개요",                  "confirm", 3,    "세 + 요"),
    ("셋이요",                   "confirm", 3,    "셋 + 이요"),
    ("네 개",                   "confirm", 4,    "순우리말 4"),
    ("다섯 개 주세요",            "confirm", 5,    "다섯"),
    ("여섯 개요",                "confirm", 6,    "여섯"),
    ("열 개",                   "confirm", 10,   "열"),
    ("스무 개",                  "confirm", 20,   "스무"),
    ("1개",                     "confirm", 1,    "숫자 1"),
    ("3개요",                    "confirm", 3,    "숫자 3 + 요"),
    ("10개",                    "confirm", 10,   "숫자 10"),
    ("2 개",                    "confirm", 2,    "숫자 + 공백 + 개"),
    ("3",                       "confirm", 3,    "숫자만"),
    ("다섯",                    "confirm", 5,    "수량 표현만"),
    ("그냥 하나면 될 것 같아요",   "confirm", 1,    "구어체 1"),
    ("많이요 열 개쯤",            "confirm", 10,   "쯤 포함"),
    ("아 두 개면 되겠다",          "confirm", 2,    "구어체 2"),
]

NON_QUANTITY_CASES = [
    ("아니요",  "deny",   None, "거절"),
    ("취소",    "cancel", None, "취소"),
    ("다른 거", "next",   None, "다음 상품"),
]

# ── 전역 verbose 플래그 ───────────────────────────────────────────────────────
VERBOSE = False


# ── LangChain 콜백: 프롬프트 전송 & raw JSON 캡처 ────────────────────────────
class _LiveLogCallback(BaseCallbackHandler):
    """LLM 호출 전후를 실시간으로 출력하는 콜백."""

    def __init__(self, show_prompt: bool = False):
        self.show_prompt = show_prompt
        self.raw_json: str = ""

    def on_llm_start(
        self, serialized: dict, prompts: list[str], **kwargs: Any
    ) -> None:
        if self.show_prompt:
            print("\n  ┌─ [LLM INPUT: System Prompt] " + "─" * 40)
            for line in prompts[0].splitlines():
                print(f"  │ {line}")
            print("  └" + "─" * 50)
        else:
            # 입력 중 user_input 줄만 추출해서 간략히 표시
            for line in prompts[0].splitlines():
                if line.strip().startswith("User input:"):
                    print(f"  → LLM 전송: {line.strip()}")
                    break

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            gen = response.generations[0][0]
            msg = gen.message  # AIMessage
            tool_calls = msg.additional_kwargs.get("tool_calls", [])
            if tool_calls:
                raw = tool_calls[0]["function"]["arguments"]
                self.raw_json = raw
                parsed = json.loads(raw)
                print("  ┌─ [LLM RAW OUTPUT: tool_call arguments] " + "─" * 30)
                for k, v in parsed.items():
                    print(f"  │  {k:<28} = {json.dumps(v, ensure_ascii=False)}")
                print("  └" + "─" * 50)
            else:
                # 일반 텍스트 응답인 경우 (드묾)
                content = getattr(gen, "text", "") or getattr(msg, "content", "")
                self.raw_json = content
                print(f"  [LLM RAW TEXT] {content[:200]}")
        except Exception as e:
            print(f"  [콜백 오류] {e}")

    def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> None:
        print(f"  [LLM ERROR] {error}")


# ── 프롬프트 빌드 (intent_agent_node 와 동일한 로직) ─────────────────────────
def _build_prompt(user_input: str, stage: str, pending_type: str) -> str:
    return INTENT_AGENT_PROMPT.format(
        user_input=user_input,
        stage=stage,
        pending_action=pending_type,
        context="",
    )


# ── 케이스 실행 (실시간 로그 포함) ───────────────────────────────────────────
def run_case(
    user_input: str,
    expected_intent: str,
    expected_qty,
    label: str,
    stage: str = "product_confirming",
    pending_type: str = "quantity_confirm",
) -> dict:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  케이스: {label!r}  |  입력: {user_input!r}")
    print(f"  stage={stage}  pending={pending_type}")
    print(sep)

    callback = _LiveLogCallback(show_prompt=VERBOSE)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, callbacks=[callback])
    structured_llm = llm.with_structured_output(IntentOutput)

    prompt = _build_prompt(user_input, stage, pending_type)

    try:
        parsed: IntentOutput = structured_llm.invoke([SystemMessage(content=prompt)])
    except Exception as e:
        print(f"  [오류] {e}")
        return _make_error_result(user_input, expected_intent, expected_qty, label)

    # 파싱 결과 출력
    print("  ┌─ [PARSED IntentOutput] " + "─" * 36)
    fields = [
        ("intent",             parsed.intent),
        ("quantity",           parsed.quantity),
        ("keywords",           parsed.keywords),
        ("exclude_keywords",   parsed.exclude_keywords),
        ("negative_constraints", parsed.negative_constraints),
        ("condition",          parsed.condition),
        ("override_platform",  parsed.override_platform),
        ("target_platforms",   parsed.target_platforms),
        ("current_option_value", parsed.current_option_value),
        ("address_text",       parsed.address_text),
        ("needs_clarification",parsed.needs_clarification),
        ("clarification_reason", parsed.clarification_reason),
        ("confidence",         parsed.confidence),
        ("immediate_response", parsed.immediate_response),
    ]
    for k, v in fields:
        print(f"  │  {k:<28} = {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else repr(v)}")
    print("  └" + "─" * 50)

    # quantity_confirm 상태에서 LLM이 null 반환 시 → Python fallback (intent_agent_node 동작 재현)
    llm_qty = parsed.quantity
    final_qty = llm_qty
    fallback_used = False
    if llm_qty is None and pending_type == "quantity_confirm" and expected_qty is not None:
        final_qty = _parse_quantity(user_input)
        fallback_used = final_qty is not None

    if fallback_used:
        print(f"  [FALLBACK] LLM qty=null -> _parse_quantity({user_input!r}) = {final_qty}")

    # 기대값 vs 실제값 판정
    ok_intent = parsed.intent == expected_intent
    ok_qty = (final_qty == expected_qty) if expected_qty is not None else (final_qty is None)
    passed = ok_intent and ok_qty

    intent_mark = "O" if ok_intent else "X"
    qty_mark    = "O" if ok_qty    else "X"
    qty_display = f"{final_qty}" + (" (fallback)" if fallback_used else "")
    print(f"  판정:")
    print(f"    intent  [{intent_mark}]  기대={expected_intent:<14} 실제={parsed.intent}")
    print(f"    quantity[{qty_mark}]  기대={str(expected_qty):<14} 실제={qty_display}")
    print(f"  {'>>> PASS <<<' if passed else '>>> FAIL <<<'}")

    return {
        "label":           label,
        "input":           user_input,
        "expected_intent": expected_intent,
        "expected_qty":    expected_qty,
        "got_intent":      parsed.intent,
        "got_qty":         final_qty,
        "fallback_used":   fallback_used,
        "immediate_response": parsed.immediate_response,
        "confidence":      parsed.confidence,
        "intent_ok":       ok_intent,
        "qty_ok":          ok_qty,
        "pass":            passed,
    }


def _make_error_result(user_input, expected_intent, expected_qty, label) -> dict:
    return {
        "label": label, "input": user_input,
        "expected_intent": expected_intent, "expected_qty": expected_qty,
        "got_intent": "ERROR", "got_qty": None,
        "immediate_response": "", "confidence": 0.0,
        "intent_ok": False, "qty_ok": False, "pass": False,
    }


# ── 요약 테이블 ───────────────────────────────────────────────────────────────
def print_summary(title: str, results: list[dict]) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}  —  요약")
    print(f"{'='*70}")
    header = f"{'입력':<24} {'기대intent':<14} {'기대qty':<8} {'실제intent':<14} {'실제qty':<8} {'신뢰도':<7} pass"
    print(header)
    print("-" * 70)
    passed = 0
    for r in results:
        mark = "O" if r["pass"] else "X"
        conf = f"{r['confidence']:.2f}" if isinstance(r["confidence"], float) else "-"
        if r["pass"]:
            passed += 1
        print(
            f"{r['input']:<24} {r['expected_intent']:<14} {str(r['expected_qty']):<8} "
            f"{r['got_intent']:<14} {str(r['got_qty']):<8} {conf:<7} [{mark}]"
        )
    print(f"\n합계: {passed}/{len(results)} 통과")


def main():
    global VERBOSE
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="LLM 프롬프트 전문 출력")
    args = parser.parse_args()
    VERBOSE = args.verbose

    print("\n" + "=" * 70)
    print("  Intent Agent - quantity_confirm 구간 실시간 로그 실험")
    print("  pending_action=quantity_confirm  stage=product_confirming 고정")
    if VERBOSE:
        print("  [VERBOSE] 프롬프트 전문 출력 ON")
    print("=" * 70)

    qty_results = [run_case(*c) for c in QUANTITY_CASES]
    non_qty_results = [run_case(*c) for c in NON_QUANTITY_CASES]

    print_summary("수량 표현 케이스", qty_results)
    print_summary("비-수량 케이스 (거절/취소/다음)", non_qty_results)

    all_results = qty_results + non_qty_results
    failed = [r for r in all_results if not r["pass"]]
    if failed:
        print(f"\n{'='*70}")
        print("  실패 케이스 목록")
        print(f"{'='*70}")
        for r in failed:
            print(f"  [{r['label']}]  입력={r['input']!r}")
            print(f"    intent:   기대={r['expected_intent']}  실제={r['got_intent']}")
            print(f"    quantity: 기대={r['expected_qty']}  실제={r['got_qty']}")
            print(f"    응답: {r['immediate_response']}")
    else:
        print("\n모든 케이스 통과!")


# ── pytest 연동 ───────────────────────────────────────────────────────────────

def test_quantity_confirm_cases():
    for user_input, expected_intent, expected_qty, label in QUANTITY_CASES:
        result = run_case(user_input, expected_intent, expected_qty, label)
        assert result["intent_ok"], (
            f"[{label}] intent: 기대={expected_intent}  실제={result['got_intent']}"
        )
        assert result["qty_ok"], (
            f"[{label}] quantity: 기대={expected_qty}  실제={result['got_qty']}"
        )


def test_non_quantity_cases():
    for user_input, expected_intent, expected_qty, label in NON_QUANTITY_CASES:
        result = run_case(user_input, expected_intent, expected_qty, label)
        assert result["intent_ok"], (
            f"[{label}] intent: 기대={expected_intent}  실제={result['got_intent']}"
        )
        assert result["qty_ok"], (
            f"[{label}] quantity: 기대={expected_qty}  실제={result['got_qty']}"
        )


if __name__ == "__main__":
    main()

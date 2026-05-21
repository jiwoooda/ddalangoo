"""
Intent Agent 인터랙티브 REPL
직접 입력 → LLM 프롬프트 / raw JSON / 파싱 결과 실시간 출력

실행: python tests/intent_repl.py
옵션:
  --stage    searching | product_confirming | payment_processing  (기본: product_confirming)
  --pending  quantity_confirm | product_confirm | payment_confirm | ...  (기본: quantity_confirm)
  --verbose  LLM에 보내는 System Prompt 전문 출력

터미널 명령:
  /stage <name>    stage 변경
  /pending <type>  pending_action 변경
  /status          현재 설정 확인
  /quit or /exit   종료
"""
import argparse
import json
import os
import sys
from typing import Any, Union

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import SystemMessage
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from src.agents.intent_agent import IntentOutput
from src.prompts.intent_prompt import INTENT_AGENT_PROMPT

VALID_STAGES = [
    "idle", "searching", "product_confirming",
    "cart_shopping", "payment_processing", "completed", "failed",
]
VALID_PENDING = [
    "product_confirm", "clarification", "payment_confirm",
    "option_select", "address_confirm", "price_change_confirm",
    "quantity_confirm", "continue_shopping", "platform_suggest",
    "payment_method_confirm", "payment_password", "null",
]


class _LiveLogCallback(BaseCallbackHandler):
    def __init__(self, show_prompt: bool = False):
        self.show_prompt = show_prompt

    def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs: Any) -> None:
        if self.show_prompt:
            print("\n  ┌─ [SYSTEM PROMPT] " + "─" * 45)
            for line in prompts[0].splitlines():
                print(f"  │ {line}")
            print("  └" + "─" * 55)
        else:
            # user_input 줄만 간략히
            for line in prompts[0].splitlines():
                stripped = line.strip()
                if stripped.startswith("User input:"):
                    print(f"\n  → LLM 전송: {stripped}")
                    break

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            gen = response.generations[0][0]
            msg = gen.message
            tool_calls = msg.additional_kwargs.get("tool_calls", [])
            if tool_calls:
                raw = tool_calls[0]["function"]["arguments"]
                parsed_raw = json.loads(raw)
                print("  ┌─ [LLM RAW · tool_call arguments] " + "─" * 30)
                for k, v in parsed_raw.items():
                    print(f"  │  {k:<28} = {json.dumps(v, ensure_ascii=False)}")
                print("  └" + "─" * 56)
            else:
                content = getattr(gen, "text", "") or getattr(msg, "content", "")
                print(f"  [LLM TEXT] {content[:300]}")
        except Exception as e:
            print(f"  [콜백 오류] {e}")

    def on_llm_error(self, error: Union[Exception, KeyboardInterrupt], **kwargs: Any) -> None:
        print(f"  [LLM ERROR] {error}")


def _call_llm(
    user_input: str,
    stage: str,
    pending_type: str,
    show_prompt: bool,
) -> IntentOutput | None:
    prompt = INTENT_AGENT_PROMPT.format(
        user_input=user_input,
        stage=stage,
        pending_action=pending_type,
        context="",
    )
    cb = _LiveLogCallback(show_prompt=show_prompt)
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, callbacks=[cb])
    structured = llm.with_structured_output(IntentOutput)
    try:
        return structured.invoke([SystemMessage(content=prompt)])
    except Exception as e:
        print(f"  [오류] {e}")
        return None


def _print_parsed(result: IntentOutput) -> None:
    print("  ┌─ [PARSED IntentOutput] " + "─" * 42)
    fields = [
        ("intent",               result.intent),
        ("quantity",             result.quantity),
        ("keywords",             result.keywords),
        ("exclude_keywords",     result.exclude_keywords),
        ("negative_constraints", result.negative_constraints),
        ("condition",            result.condition),
        ("override_platform",    result.override_platform),
        ("target_platforms",     result.target_platforms),
        ("current_option_value", result.current_option_value),
        ("address_text",         result.address_text),
        ("needs_clarification",  result.needs_clarification),
        ("clarification_reason", result.clarification_reason),
        ("confidence",           result.confidence),
        ("immediate_response",   result.immediate_response),
    ]
    for k, v in fields:
        val = repr(v) if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        print(f"  │  {k:<28} = {val}")
    print("  └" + "─" * 56)


def _print_status(stage: str, pending: str, verbose: bool) -> None:
    print(f"\n  현재 설정  stage={stage}  pending={pending}  verbose={verbose}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Intent Agent REPL")
    parser.add_argument("--stage",   default="product_confirming", choices=VALID_STAGES)
    parser.add_argument("--pending", default="quantity_confirm",
                        choices=VALID_PENDING + ["null"])
    parser.add_argument("--verbose", action="store_true", help="System Prompt 전문 출력")
    args = parser.parse_args()

    stage   = args.stage
    pending = args.pending
    verbose = args.verbose

    print("=" * 62)
    print("  Intent Agent REPL  —  입력하면 즉시 파싱 결과 출력")
    print("  /stage <name>  /pending <type>  /status  /quit")
    print("=" * 62)
    _print_status(stage, pending, verbose)
    print()

    while True:
        try:
            user_input = input("입력 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not user_input:
            continue

        # ── 내부 명령어 ──
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit", "/q"):
                print("종료합니다.")
                break
            elif cmd == "/stage":
                if arg in VALID_STAGES:
                    stage = arg
                    print(f"  stage → {stage}")
                else:
                    print(f"  유효한 stage: {VALID_STAGES}")
            elif cmd == "/pending":
                if arg in VALID_PENDING:
                    pending = arg
                    print(f"  pending → {pending}")
                else:
                    print(f"  유효한 pending: {VALID_PENDING}")
            elif cmd == "/verbose":
                verbose = not verbose
                print(f"  verbose → {verbose}")
            elif cmd == "/status":
                _print_status(stage, pending, verbose)
            else:
                print(f"  알 수 없는 명령: {cmd}")
            continue

        # ── LLM 호출 ──
        print(f"\n{'─'*62}")
        result = _call_llm(user_input, stage, pending, verbose)
        if result:
            _print_parsed(result)
        print()


if __name__ == "__main__":
    main()

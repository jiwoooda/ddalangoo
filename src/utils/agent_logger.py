"""
Agent Logger — 에이전트 실행 추적 로거.

LOG_AGENT_TRACE=true 환경변수로 활성화.
logs/<session_id>_<timestamp>.log  : 사람이 읽기 쉬운 텍스트
logs/<session_id>_<timestamp>.jsonl: 분석용 구조화 데이터
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


class AgentLogger:
    def __init__(self):
        self._enabled: bool = False
        self._txt_path: Path | None = None
        self._jsonl_path: Path | None = None
        self._turn: int = 0

    # ── 세션 초기화 ─────────────────────────────────────────────
    def start_session(self, session_id: str, log_dir: str = "logs") -> None:
        if not os.getenv("LOG_AGENT_TRACE", "").lower() in ("1", "true", "yes"):
            return
        self._enabled = True
        self._turn = 0

        Path(log_dir).mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(log_dir) / f"{session_id}_{ts}"
        self._txt_path = base.with_suffix(".log")
        self._jsonl_path = base.with_suffix(".jsonl")

        header = (
            f"{'='*60}\n"
            f"  SESSION: {session_id}\n"
            f"  STARTED: {datetime.now().isoformat()}\n"
            f"{'='*60}\n"
        )
        self._txt_path.write_text(header, encoding="utf-8")
        self._log_jsonl({"event": "session_start", "session_id": session_id})

    def new_turn(self, user_input: str) -> None:
        if not self._enabled:
            return
        self._turn += 1
        sep = f"\n{'─'*60}\n[TURN {self._turn}] 사용자: {user_input}\n{'─'*60}\n"
        self._append_txt(sep)
        self._log_jsonl({"event": "turn_start", "turn": self._turn, "user_input": user_input})

    # ── 각 에이전트 로깅 ────────────────────────────────────────
    def log_intent(
        self,
        user_input: str,
        stage: str,
        pending_action: Any,
        output: dict,
    ) -> None:
        if not self._enabled:
            return
        pending_type = (pending_action or {}).get("type", "-") if isinstance(pending_action, dict) else "-"
        lines = [
            "[intent_agent]",
            f"  입력  | user_input={repr(user_input)}  stage={stage}  pending={pending_type}",
            f"  출력  | intent={output.get('intent')}  quantity={output.get('quantity')}  "
            f"confidence={output.get('confidence', 0):.2f}  needs_clarification={output.get('needs_clarification')}",
            f"  keywords={output.get('keywords')}",
            f"  immediate_response={repr(output.get('immediate_response'))}",
        ]
        if output.get("clarification_reason"):
            lines.append(f"  clarification_reason={repr(output.get('clarification_reason'))}")
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({"event": "intent_agent", "turn": self._turn, "user_input": user_input,
                         "stage": stage, "pending_type": pending_type, **output})

    def log_router(self, from_node: str, to_node: str, intent: str, stage: str, pending_type: str) -> None:
        if not self._enabled:
            return
        line = f"[router]  {from_node} → {to_node}  (intent={intent}  stage={stage}  pending={pending_type})\n"
        self._append_txt(line)
        self._log_jsonl({"event": "router", "turn": self._turn,
                         "from": from_node, "to": to_node,
                         "intent": intent, "stage": stage, "pending_type": pending_type})

    def log_platform_agent(self, inputs: dict, outputs: dict) -> None:
        if not self._enabled:
            return
        lines = [
            "[platform_agent]",
            f"  입력  | keywords={inputs.get('keywords')}  intent={inputs.get('intent')}  "
            f"tried={inputs.get('tried_platforms')}",
            f"  출력  | stage={outputs.get('stage')}  pending={_ptype(outputs.get('pending_action'))}  "
            f"results_count={len(outputs.get('search_results') or [])}",
        ]
        if (outputs.get("pending_action") or {}).get("message"):
            lines.append(f"  message={repr(outputs['pending_action']['message'])}")
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({"event": "platform_agent", "turn": self._turn, **inputs,
                         "outputs_stage": outputs.get("stage"),
                         "outputs_pending": _ptype(outputs.get("pending_action")),
                         "outputs_results_count": len(outputs.get("search_results") or [])})

    def log_product_agent(self, inputs: dict, outputs: dict) -> None:
        if not self._enabled:
            return
        selected = outputs.get("selected_product") or {}
        lines = [
            "[product_agent]",
            f"  입력  | intent={inputs.get('intent')}  search_results={inputs.get('results_count')}건",
            f"  출력  | stage={outputs.get('stage')}  pending={_ptype(outputs.get('pending_action'))}",
            f"  selected={selected.get('product_name')}  idx={outputs.get('current_product_index')}",
        ]
        if outputs.get("explanation"):
            lines.append(f"  explanation={repr(outputs['explanation'][:120])}{'...' if len(outputs.get('explanation',''))>120 else ''}")
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({"event": "product_agent", "turn": self._turn, **inputs,
                         "outputs_stage": outputs.get("stage"),
                         "outputs_pending": _ptype(outputs.get("pending_action")),
                         "selected_product_name": selected.get("product_name"),
                         "explanation_snippet": (outputs.get("explanation") or "")[:120]})

    def log_payment_agent(self, inputs: dict, outputs: dict) -> None:
        if not self._enabled:
            return
        lines = [
            "[payment_agent]",
            f"  입력  | intent={inputs.get('intent')}  pending={inputs.get('pending_type')}  quantity={inputs.get('quantity')}",
            f"  출력  | stage={outputs.get('stage')}  pending={_ptype(outputs.get('pending_action'))}",
        ]
        if (outputs.get("pending_action") or {}).get("message"):
            lines.append(f"  message={repr(outputs['pending_action']['message'])}")
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({"event": "payment_agent", "turn": self._turn, **inputs,
                         "outputs_stage": outputs.get("stage"),
                         "outputs_pending": _ptype(outputs.get("pending_action"))})

    def log_respond(self, message: str, stage: str, pending_action: Any) -> None:
        if not self._enabled:
            return
        lines = [
            "[respond]",
            f"  stage={stage}  pending={_ptype(pending_action)}",
            f"  >>> {message}",
            "",
        ]
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({"event": "respond", "turn": self._turn,
                         "stage": stage, "pending_type": _ptype(pending_action), "message": message})

    # ── 내부 헬퍼 ───────────────────────────────────────────────
    def _append_txt(self, text: str) -> None:
        if self._txt_path:
            with self._txt_path.open("a", encoding="utf-8") as f:
                f.write(text)

    def _log_jsonl(self, data: dict) -> None:
        if self._jsonl_path:
            with self._jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def log_path(self) -> str | None:
        return str(self._txt_path) if self._txt_path else None


def _ptype(pending_action: Any) -> str:
    if isinstance(pending_action, dict):
        return pending_action.get("type", "-")
    return "-"


# 글로벌 싱글턴
agent_logger = AgentLogger()

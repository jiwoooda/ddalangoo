"""
Agent Logger — 에이전트 실행 추적 로거.

LOG_AGENT_TRACE=true 환경변수로 활성화.
logs/<session_id>_<timestamp>.log  : 사람이 읽기 쉬운 텍스트
logs/<session_id>_<timestamp>.jsonl: 분석용 구조화 데이터
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AgentLogger:
    def __init__(self):
        self._enabled: bool = False
        self._console: bool = False
        self._txt_path: Path | None = None
        self._jsonl_path: Path | None = None
        self._turn: int = 0
        # context_agent가 로컬 컨텍스트 조회와 build_preference_context를
        # 스레드로 동시에 돌리면서 두 브랜치가 같은 로그 파일에 동시에
        # append할 수 있게 됐다 — 파일 쓰기가 끼어들어(interleave) 줄이
        # 깨지지 않도록 write 구간만 락으로 보호한다.
        self._write_lock = threading.Lock()

    def start_session(self, session_id: str, log_dir: str = "logs", console: bool = False) -> None:
        env_on = os.getenv("LOG_AGENT_TRACE", "").lower() in ("1", "true", "yes")
        if not (env_on or console):
            return
        self._enabled = True
        self._console = console
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

    def log_intent(self, user_input: str, stage: str, pending_action: Any, output: dict) -> None:
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

    def log_scoring_agent(self, inputs: dict, outputs: dict) -> None:
        """
        Stage4(축 가중치 판단 + 선호도 매칭 + 집계) 근거 로깅. tier1 배제는
        Stage3(_filter_results)에서 이미 끝났고, 여기는 통과한 후보들 간의
        상대 순위 근거만 남긴다 — 왜 이 순위인지 역추적용.
        """
        if not self._enabled:
            return
        axis_weights = outputs.get("axis_weights") or []
        lines = [
            "[scoring_agent]",
            f"  입력  | 후보 {inputs.get('candidates')}개  keywords={inputs.get('keywords')}  "
            f"condition={inputs.get('condition')}  soft_preferences={inputs.get('soft_preferences')}",
        ]
        for aw in axis_weights:
            lines.append(f"  axis  | {aw.get('axis')}={aw.get('weight')}  근거={repr(aw.get('reasoning', '')[:80])}")
        if outputs.get("conflict_note"):
            lines.append(f"  충돌  | {repr(outputs['conflict_note'][:120])}")
        lines.append(
            f"  결과  | 1위={outputs.get('ranked_top')}  score={outputs.get('ranked_top_score')}"
        )
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({
            "event": "scoring_agent", "turn": self._turn,
            **inputs,
            "axis_weights": axis_weights,
            "weights_normalized": outputs.get("weights_normalized"),
            "conflict_note": outputs.get("conflict_note"),
            "ranked_top": outputs.get("ranked_top"),
            "ranked_top_score": outputs.get("ranked_top_score"),
        })

    def log_scoring_fallback(self, inputs: dict, error: str) -> None:
        """
        Stage4 스코어링 실패 → 원본 순서로 폴백한 경우 전용 로그.
        기존엔 log()로 텍스트만 남겨서 "폴백이 몇 번 발생했는지"를 집계하려면
        문자열 매칭에 의존해야 했다 — event="scoring_agent_fallback"로 구조화
        해서 scripts/check_fallback_rate.py가 안정적으로 집계할 수 있게 한다.
        """
        if not self._enabled:
            return
        lines = [
            "[scoring_agent] 폴백 (원본 순서 유지)",
            f"  입력  | 후보 {inputs.get('candidates')}개  keywords={inputs.get('keywords')}",
            f"  에러  | {error}",
        ]
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({
            "event": "scoring_agent_fallback", "turn": self._turn,
            "candidates": inputs.get("candidates"), "keywords": inputs.get("keywords"),
            "condition": inputs.get("condition"), "error": error,
        })

    # ── 실패 관측성 — Technical Retry / Fallback / Recovery / Graceful Degradation ──
    # docs/resilience_plan.md Phase 2 참고. 노드 진입 시점에는 직전 실패의 예외
    # 타입을 알 수 없으므로, "재시도 시작"과 "실패 발생"을 별도 메서드로 분리한다.

    def log_retry_attempt_started(self, node: str, node_attempt: int) -> None:
        """노드 진입부에서 node_attempt(=runtime.execution_info.node_attempt) > 1일 때만 호출."""
        if not self._enabled:
            return
        self._append_txt(f"[{node}] 재시도 진입 | attempt={node_attempt}\n")
        self._log_jsonl({"event": "retry_attempt_started", "turn": self._turn, "node": node, "node_attempt": node_attempt})

    def log_transient_failure(self, node: str, node_attempt: int, exception_type: str) -> None:
        """일시적 기술 오류(TRANSIENT_TECHNICAL) 발생 시, re-raise 직전 호출.
        여기서만 실제 예외 객체를 알 수 있다 — RetryPolicy가 이어서 노드를 재실행한다."""
        if not self._enabled:
            return
        self._append_txt(f"[{node}] Technical Retry 대상 실패 | attempt={node_attempt}  exception={exception_type}\n")
        self._log_jsonl({
            "event": "transient_failure", "turn": self._turn,
            "node": node, "node_attempt": node_attempt, "exception_type": exception_type,
        })

    def log_retry_exhausted(self, node: str, exception_type: str) -> None:
        """RetryPolicy의 max_attempts 소진 후 error_handler 내부에서 호출."""
        if not self._enabled:
            return
        self._append_txt(f"[{node}] Retry 소진 → Graceful Degradation | exception={exception_type}\n")
        self._log_jsonl({"event": "retry_exhausted", "turn": self._turn, "node": node, "exception_type": exception_type})

    def log_permanent_technical_error(self, node: str, exception_type: str) -> None:
        """PERMANENT_TECHNICAL(401 등, 재시도 대상 아님) — error_handler 내부에서 호출."""
        if not self._enabled:
            return
        self._append_txt(f"[{node}] 영구적 기술 오류(재시도 안함) | exception={exception_type}\n")
        self._log_jsonl({"event": "permanent_technical_error", "turn": self._turn, "node": node, "exception_type": exception_type})

    def log_source_fallback(self, from_source: str, to_source: str, reason: str) -> None:
        """Fallback: 다른 데이터 소스/도구로 전환 (예: meta_mcp_client의 원격MCP→로컬MCP→네이버→컬리)."""
        if not self._enabled:
            return
        self._append_txt(f"[source_fallback] {from_source} → {to_source} | reason={reason}\n")
        self._log_jsonl({
            "event": "source_fallback", "turn": self._turn,
            "from_source": from_source, "to_source": to_source, "reason": reason,
        })

    def log_quality_regeneration(self, node: str, reason: str) -> None:
        """Recovery: 품질 재생성(예: response_agent의 Reflection 실패 → Haiku 재생성)."""
        if not self._enabled:
            return
        self._append_txt(f"[{node}] 품질 재생성(Recovery) | reason={reason}\n")
        self._log_jsonl({"event": "quality_regeneration", "turn": self._turn, "node": node, "reason": reason})

    def log_graceful_degradation(self, node: str, reason: str, stage: str) -> None:
        """Graceful Degradation: 기능을 축소해도 유효 응답 반환 (예: baseline ranking, 코드 기반 설명)."""
        if not self._enabled:
            return
        self._append_txt(f"[{node}] Graceful Degradation | stage={stage}  reason={reason}\n")
        self._log_jsonl({
            "event": "graceful_degradation", "turn": self._turn,
            "node": node, "failure_stage": stage, "reason": reason,
        })

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

    def log(self, text: str) -> None:
        if not self._enabled:
            return
        self._append_txt(text + "\n")
        self._log_jsonl({"event": "log", "turn": self._turn, "text": text})

    def log_fallback_event(self, event: dict[str, Any]) -> None:
        """Best-effort persistent fallback telemetry with an allowlisted schema."""
        allowed = (
            "session_ref", "stage", "pending_type", "intent", "failure_kind",
            "failure_code", "failure_source", "retryability", "side_effect_risk",
            "recovery_attempts", "recovery_status", "recovery_fingerprint",
            "final_fallback_action", "response_generation_type",
        )
        try:
            path = Path(os.getenv("FALLBACK_EVENT_LOG_PATH", "logs/fallback_events.jsonl"))
            record = {key: event.get(key) for key in allowed}
            record["timestamp"] = datetime.now(timezone.utc).isoformat()
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._write_lock, path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            return

    def log_context_agent(self, inputs: dict, outputs: dict) -> None:
        if not self._enabled:
            return
        pref = outputs.get("preference_context") or {}
        summary = pref.get("summary") or ""
        kw_summary = pref.get("keyword_summary") or ""
        brands = [b.get("brand") for b in (pref.get("preferred_brands") or [])[:3]]
        price_avg = (pref.get("price_range") or {}).get("avg")
        repurchase = (pref.get("repurchase_patterns") or [])[:2]
        keyword_history_count = len(pref.get("keyword_history") or [])

        lines = [
            "[context_agent]",
            f"  입력  | stage={inputs.get('stage')}  intent={inputs.get('intent')}  "
            f"user_id={inputs.get('user_id')}  keywords={inputs.get('keywords')}",
            f"  구매  | 이력 {inputs.get('purchase_count', '?')}건  "
            f"retrieval_mode={inputs.get('retrieval_mode', '?')}  "
            f"캐시={'HIT' if inputs.get('cache_hit') else 'MISS'}",
            f"  선호도| 브랜드={brands}  평균가={price_avg:,}원" if price_avg else f"  선호도| 브랜드={brands}  (이력 없음)",
        ]
        if repurchase:
            lines.append(f"        | 재구매패턴={repurchase}")
        if summary:
            snippet = summary[:120] + ("..." if len(summary) > 120 else "")
            lines.append(f"  요약  | {snippet}")
        if kw_summary:
            kw_snippet = kw_summary[:120] + ("..." if len(kw_summary) > 120 else "")
            lines.append(f"  키워드| ({keyword_history_count}건 이력) {kw_snippet}")
        elif inputs.get("keywords"):
            lines.append(f"  키워드| 이력 {keyword_history_count}건 (LLM 요약 없음)")

        # tier1(안전)/tier2(명시적 배제)/tier3(뉘앙스) — 왜 이 keywords/exclude_keywords가
        # 됐는지 역추적할 수 있도록 남긴다. tier1은 특히 100% 설명 가능해야 한다.
        keyword_additions = pref.get("keyword_additions") or []
        exclude_additions = pref.get("exclude_additions") or []
        safety_constraints = pref.get("safety_constraints") or []
        soft_preferences = pref.get("soft_preferences") or []
        if keyword_additions or exclude_additions or safety_constraints or soft_preferences:
            lines.append(
                f"  tier   | keyword+={keyword_additions}  exclude+={exclude_additions}  "
                f"safety={safety_constraints}  soft={soft_preferences}"
            )
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({
            "event": "context_agent", "turn": self._turn,
            **inputs,
            "preference_summary": summary,
            "keyword_summary": kw_summary,
            "preferred_brands": brands,
            "price_avg": price_avg,
            "keyword_additions": keyword_additions,
            "exclude_additions": exclude_additions,
            "safety_constraints": safety_constraints,
            "soft_preferences": soft_preferences,
        })

    def log_reorder_agent(self, inputs: dict, outputs: dict) -> None:
        if not self._enabled:
            return
        resolution_type = outputs.get("resolution_type", "-")
        selected = outputs.get("selected_candidate") or {}
        candidates = outputs.get("candidates") or []
        lines = [
            "[reorder_agent]",
            f"  입력  | pending_type={inputs.get('pending_type', '-')}  "
            f"user_id={inputs.get('user_id')}  keywords={inputs.get('keywords')}",
            f"  결과  | resolution_type={resolution_type}  후보 {len(candidates)}개",
        ]
        if resolution_type == "resolved" and selected:
            lines.append(
                f"  선택  | {selected.get('product_name')}  "
                f"{selected.get('price_at_purchase', 0):,}원  "
                f"({selected.get('platform', '-')})"
            )
        elif resolution_type == "ambiguous":
            names = [c.get("product_name") for c in candidates[:3]]
            lines.append(f"  모호  | 후보 목록: {names}")
        elif resolution_type == "no_match":
            lines.append(f"  없음  | 구매이력에서 매칭 없음 → product_agent로 fallback")
        lines.append(f"  stage={outputs.get('stage')}  pending={_ptype(outputs.get('pending_action'))}")
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({
            "event": "reorder_agent", "turn": self._turn,
            **inputs,
            "resolution_type": resolution_type,
            "candidate_count": len(candidates),
            "selected_product_name": selected.get("product_name"),
        })

    def log_memory_agent(self, inputs: dict, outputs: dict) -> None:
        if not self._enabled:
            return
        pref = outputs.get("preference_context") or {}
        summary = pref.get("summary") or ""
        kw_summary = pref.get("keyword_summary") or ""
        brands = [b.get("brand") for b in (pref.get("preferred_brands") or [])[:3]]
        price_avg = (pref.get("price_range") or {}).get("avg")
        repurchase = (pref.get("repurchase_patterns") or [])[:2]
        keyword_history_count = len(pref.get("keyword_history") or [])

        lines = [
            "[memory_agent]",
            f"  입력  | stage={inputs.get('stage')}  intent={inputs.get('intent')}  "
            f"user_id={inputs.get('user_id')}  keywords={inputs.get('keywords')}",
            f"  mock  | 구매이력 {inputs.get('history_count', '?')}건  "
            f"캐시={'HIT' if inputs.get('cache_hit') else 'MISS'}",
            f"  선호도| 브랜드={brands}  평균가={price_avg:,}원" if price_avg else f"  선호도| 브랜드={brands}",
        ]
        if repurchase:
            lines.append(f"        | 재구매패턴={repurchase}")
        if summary:
            snippet = summary[:120] + ("..." if len(summary) > 120 else "")
            lines.append(f"  요약  | {snippet}")
        if kw_summary:
            kw_snippet = kw_summary[:120] + ("..." if len(kw_summary) > 120 else "")
            lines.append(f"  키워드| ({keyword_history_count}건 이력) {kw_snippet}")
        elif inputs.get('keywords'):
            lines.append(f"  키워드| 이력 {keyword_history_count}건 (요약 없음)")
        self._append_txt("\n".join(lines) + "\n")
        self._log_jsonl({
            "event": "memory_agent", "turn": self._turn,
            **inputs,
            "preference_summary": summary,
            "keyword_summary": kw_summary,
            "preferred_brands": brands,
            "price_avg": price_avg,
        })

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

    def _append_txt(self, text: str) -> None:
        if self._txt_path:
            with self._write_lock, self._txt_path.open("a", encoding="utf-8") as f:
                f.write(text)
        if self._console:
            print(text, end="", flush=True)

    def _log_jsonl(self, data: dict) -> None:
        if self._jsonl_path:
            # 이벤트마다 타임스탬프를 찍어둬야 turn_start~respond 사이 소요시간을
            # 나중에 scripts/check_turn_latency.py가 역산할 수 있다.
            with self._write_lock, self._jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(), **data}, ensure_ascii=False) + "\n")

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


agent_logger = AgentLogger()

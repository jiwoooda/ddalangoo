"""
Failure-Path 회복탄력성 지표 집계 — agent_logger가 남긴 .jsonl 로그에서
Technical Retry / Fallback / Recovery / Graceful Degradation 이벤트를
읽어 지표를 계산한다 (docs/resilience_plan.md Phase 2 참고).

scripts/check_fallback_rate.py와 동일한 로그 스캔 규칙(_DEFAULT_LOG_DIRS,
_iter_events)을 그대로 재사용한다 — Stage4 스코어링 폴백만 보는
check_fallback_rate.py와 달리, 이 스크립트는 전체 노드에 걸친 실패
관측 이벤트(retry_attempt_started/transient_failure/retry_exhausted/
permanent_technical_error/source_fallback/quality_regeneration/
graceful_degradation)를 집계한다.

사용법:
  python scripts/check_resilience_metrics.py
  python scripts/check_resilience_metrics.py --log-dir ../../../logs
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/vendor/ddalangoo-langgraph

_DEFAULT_LOG_DIRS = [
    BASE_DIR / "logs",
    BASE_DIR.parent.parent / "logs",       # backend/logs
    BASE_DIR.parent.parent.parent / "logs",  # 레포 루트 logs
]

_RESILIENCE_EVENTS = frozenset({
    "retry_attempt_started",
    "transient_failure",
    "retry_exhausted",
    "permanent_technical_error",
    "source_fallback",
    "quality_regeneration",
    "graceful_degradation",
    "turn_start",
})


def _iter_events(log_dirs: list[Path]):
    for log_dir in log_dirs:
        if not log_dir.is_dir():
            continue
        for path in sorted(log_dir.glob("*.jsonl")):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield path, json.loads(line)
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue


def compute_resilience_stats(log_dirs: list[Path] | None = None) -> dict:
    log_dirs = log_dirs or _DEFAULT_LOG_DIRS

    turns = 0
    by_node_transient_failure: Counter = Counter()
    by_node_retry_exhausted: Counter = Counter()
    by_node_permanent_error: Counter = Counter()
    by_node_quality_regeneration: Counter = Counter()
    by_node_graceful_degradation: Counter = Counter()
    by_stage_graceful_degradation: Counter = Counter()
    source_fallback_paths: Counter = Counter()
    files_seen: set[Path] = set()

    for path, event in _iter_events(log_dirs):
        ev = event.get("event")
        if ev not in _RESILIENCE_EVENTS:
            continue
        files_seen.add(path)

        if ev == "turn_start":
            turns += 1
        elif ev == "transient_failure":
            by_node_transient_failure[event.get("node", "unknown")] += 1
        elif ev == "retry_exhausted":
            by_node_retry_exhausted[event.get("node", "unknown")] += 1
        elif ev == "permanent_technical_error":
            by_node_permanent_error[event.get("node", "unknown")] += 1
        elif ev == "quality_regeneration":
            by_node_quality_regeneration[event.get("node", "unknown")] += 1
        elif ev == "graceful_degradation":
            by_node_graceful_degradation[event.get("node", "unknown")] += 1
            by_stage_graceful_degradation[event.get("failure_stage", "unknown")] += 1
        elif ev == "source_fallback":
            path_key = f"{event.get('from_source', '?')}→{event.get('to_source', '?')}"
            source_fallback_paths[path_key] += 1

    total_transient_attempts = sum(by_node_transient_failure.values())
    total_retry_exhausted = sum(by_node_retry_exhausted.values())
    # transient_failure는 "재시도 대상 실패"마다 찍히고, retry_exhausted는
    # max_attempts까지 다 실패했을 때만 찍힌다 — 둘의 차이가 "재시도로
    # 회복된(2~3차 시도에서 성공한) 횟수"의 근사치다. 정확한 시도 시퀀스
    # 페어링은 하지 않는다(로그만으로는 어느 transient_failure가 어느
    # node_attempt에 속했는지 이미 node_attempt 필드로 알 수 있지만,
    # 동시 실행 세션이 섞이면 완벽한 페어링은 어려움).
    retry_recovered_estimate = max(total_transient_attempts - total_retry_exhausted, 0)

    total_degradations = sum(by_node_graceful_degradation.values())
    degradation_rate = (total_degradations / turns) if turns else None

    return {
        "turns": turns,
        "technical_retry": {
            "transient_failures_by_node": dict(by_node_transient_failure.most_common()),
            "retry_exhausted_by_node": dict(by_node_retry_exhausted.most_common()),
            "retry_recovered_estimate": retry_recovered_estimate,
        },
        "permanent_technical_error_by_node": dict(by_node_permanent_error.most_common()),
        "source_fallback_paths": dict(source_fallback_paths.most_common()),
        "quality_regeneration_by_node": dict(by_node_quality_regeneration.most_common()),
        "graceful_degradation": {
            "by_node": dict(by_node_graceful_degradation.most_common()),
            "by_failure_stage": dict(by_stage_graceful_degradation.most_common()),
            "total": total_degradations,
            "rate_per_turn": degradation_rate,
        },
        "files_scanned": len(files_seen),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Failure-Path 회복탄력성 지표 집계")
    parser.add_argument("--log-dir", action="append", help="추가로 훑을 로그 디렉토리 (여러 번 지정 가능)")
    args = parser.parse_args()

    log_dirs = list(_DEFAULT_LOG_DIRS)
    if args.log_dir:
        log_dirs.extend(Path(d) for d in args.log_dir)

    stats = compute_resilience_stats(log_dirs)

    print(f"스캔한 로그 디렉토리: {[str(d) for d in log_dirs if d.is_dir()]}")
    print(f"관측 이벤트가 있는 파일 수: {stats['files_scanned']}")
    print(f"{'─'*50}")
    if stats["files_scanned"] == 0:
        print("관측 이벤트가 없습니다 (LOG_AGENT_TRACE=true로 세션을 돌려야 쌓입니다).")
        return

    print(f"턴 수: {stats['turns']}")

    tr = stats["technical_retry"]
    print("\n[Technical Retry]")
    print(f"  일시적 실패(재시도 대상) 노드별: {tr['transient_failures_by_node']}")
    print(f"  Retry 소진 노드별: {tr['retry_exhausted_by_node']}")
    print(f"  재시도로 회복 추정치: {tr['retry_recovered_estimate']}건")

    if stats["permanent_technical_error_by_node"]:
        print("\n[Permanent Technical Error] (재시도 대상 아님)")
        print(f"  노드별: {stats['permanent_technical_error_by_node']}")

    if stats["source_fallback_paths"]:
        print("\n[Fallback] 데이터 소스 전환 경로별 건수")
        for path_key, n in stats["source_fallback_paths"].items():
            print(f"  {n:>3}건  {path_key}")

    if stats["quality_regeneration_by_node"]:
        print("\n[Recovery] 품질 재생성 노드별 건수")
        print(f"  {stats['quality_regeneration_by_node']}")

    gd = stats["graceful_degradation"]
    print("\n[Graceful Degradation]")
    print(f"  노드별: {gd['by_node']}")
    print(f"  실패 단계별: {gd['by_failure_stage']}")
    if gd["rate_per_turn"] is not None:
        print(f"  턴당 축소 응답 비율: {gd['rate_per_turn']*100:.1f}%")


if __name__ == "__main__":
    main()

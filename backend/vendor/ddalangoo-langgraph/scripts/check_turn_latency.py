"""
턴당 총 소요시간 집계 — agent_logger의 .jsonl에서 각 턴의 "turn_start"부터
"respond"까지 걸린 시간을 역산한다.

배경: 턴당 LLM 콜이 최대 5개까지 순차로 쌓이는데, 실제로 사용자가 체감하는
지연이 얼마인지 측정하는 인프라가 없었다. 최적화(예: context_agent의
안전동기화+분류 병렬화)를 논하기 전에, 먼저 이걸로 실측치를 확보한다.

agent_logger가 매 이벤트에 ts(ISO 타임스탬프)를 찍어두므로, 같은
(파일, turn) 안에서 "turn_start" 이벤트 시각과 "respond" 이벤트 시각의
차이를 턴 전체 소요시간으로 본다.

사용법:
  python scripts/check_turn_latency.py
  python scripts/check_turn_latency.py --log-dir ../../../logs
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/vendor/ddalangoo-langgraph

_DEFAULT_LOG_DIRS = [
    BASE_DIR / "logs",
    BASE_DIR.parent.parent / "logs",         # backend/logs
    BASE_DIR.parent.parent.parent / "logs",  # 레포 루트 logs
]


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


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def compute_turn_latencies(log_dirs: list[Path] | None = None) -> dict:
    log_dirs = log_dirs or _DEFAULT_LOG_DIRS
    # (파일, turn) -> {"start": ts, "end": ts}
    turns: dict[tuple[Path, int], dict[str, datetime]] = {}

    for path, event in _iter_events(log_dirs):
        turn = event.get("turn")
        if turn is None:
            continue
        ts = _parse_ts(event.get("ts"))
        if ts is None:
            continue
        key = (path, turn)
        entry = turns.setdefault(key, {})
        if event.get("event") == "turn_start":
            entry["start"] = ts
        elif event.get("event") == "respond":
            entry["end"] = ts  # 같은 턴에 respond가 여러 번이면 마지막 것

    durations_ms = sorted(
        (e["end"] - e["start"]).total_seconds() * 1000
        for e in turns.values()
        if "start" in e and "end" in e and e["end"] >= e["start"]
    )

    if not durations_ms:
        return {"n": 0}

    n = len(durations_ms)
    return {
        "n": n,
        "mean_ms": round(sum(durations_ms) / n, 1),
        "p50_ms": round(durations_ms[n // 2], 1),
        "p90_ms": round(durations_ms[min(n - 1, int(n * 0.9))], 1),
        "max_ms": round(durations_ms[-1], 1),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="턴당 총 소요시간(turn_start~respond) 집계")
    parser.add_argument("--log-dir", action="append", help="추가로 훑을 로그 디렉토리 (여러 번 지정 가능)")
    args = parser.parse_args()

    log_dirs = list(_DEFAULT_LOG_DIRS)
    if args.log_dir:
        log_dirs.extend(Path(d) for d in args.log_dir)

    stats = compute_turn_latencies(log_dirs)

    print(f"스캔한 로그 디렉토리: {[str(d) for d in log_dirs if d.is_dir()]}")
    print(f"{'─'*50}")
    if stats["n"] == 0:
        print(
            "turn_start~respond 쌍이 없습니다 (LOG_AGENT_TRACE=true로 세션을 "
            "돌려야 쌓이고, 이 스크립트 실행 전 배포된 agent_logger.py여야 "
            "ts 필드가 찍힙니다)."
        )
        return
    print(f"측정된 턴 수: {stats['n']}")
    print(f"평균: {stats['mean_ms']}ms   p50: {stats['p50_ms']}ms   "
          f"p90: {stats['p90_ms']}ms   최대: {stats['max_ms']}ms")


if __name__ == "__main__":
    main()

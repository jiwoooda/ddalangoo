"""
Stage4(product_agent 스코어링) 폴백 발생률 집계 — agent_logger가 남긴
.jsonl 로그를 읽어서 "성공(scoring_agent) vs 폴백(scoring_agent_fallback)"
비율을 계산한다.

배경: 이전엔 폴백이 발생해도 로그에만 텍스트로 남고 아무도 안 보는
"조용한 폴백"이었다 — 이 스크립트로 그 발생률을 눈에 보이게 한다.
evals/dashboard.py의 "운영 지표" 탭에서도 이 로직을 재사용한다.

사용법:
  python scripts/check_fallback_rate.py
  python scripts/check_fallback_rate.py --log-dir ../../../logs
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/vendor/ddalangoo-langgraph

# agent_logger.start_session(log_dir="logs")가 기본값이라, 실행 위치(cwd)에
# 따라 여러 곳에 log이 쌓여있을 수 있다 — 알려진 위치를 전부 훑는다.
_DEFAULT_LOG_DIRS = [
    BASE_DIR / "logs",
    BASE_DIR.parent.parent / "logs",       # backend/logs
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


def compute_fallback_stats(log_dirs: list[Path] | None = None) -> dict:
    log_dirs = log_dirs or _DEFAULT_LOG_DIRS
    counts = Counter()
    fallback_errors = Counter()
    files_seen: set[Path] = set()

    for path, event in _iter_events(log_dirs):
        ev = event.get("event")
        if ev == "scoring_agent":
            counts["success"] += 1
            files_seen.add(path)
        elif ev == "scoring_agent_fallback":
            counts["fallback"] += 1
            fallback_errors[event.get("error", "unknown")] += 1
            files_seen.add(path)

    total = counts["success"] + counts["fallback"]
    rate = (counts["fallback"] / total) if total else None
    return {
        "total": total,
        "success": counts["success"],
        "fallback": counts["fallback"],
        "fallback_rate": rate,
        "fallback_error_breakdown": dict(fallback_errors.most_common()),
        "files_scanned": len(files_seen),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Stage4 스코어링 폴백 발생률 집계")
    parser.add_argument("--log-dir", action="append", help="추가로 훑을 로그 디렉토리 (여러 번 지정 가능)")
    args = parser.parse_args()

    log_dirs = list(_DEFAULT_LOG_DIRS)
    if args.log_dir:
        log_dirs.extend(Path(d) for d in args.log_dir)

    stats = compute_fallback_stats(log_dirs)

    print(f"스캔한 로그 디렉토리: {[str(d) for d in log_dirs if d.is_dir()]}")
    print(f"scoring_agent 이벤트가 있는 파일 수: {stats['files_scanned']}")
    print(f"{'─'*50}")
    if stats["total"] == 0:
        print("scoring_agent 이벤트가 없습니다 (LOG_AGENT_TRACE=true로 세션을 돌려야 쌓입니다).")
        return
    print(f"성공: {stats['success']}  폴백: {stats['fallback']}  총: {stats['total']}")
    print(f"폴백률: {stats['fallback_rate']*100:.1f}%")
    if stats["fallback_error_breakdown"]:
        print("폴백 원인별 건수:")
        for err, n in stats["fallback_error_breakdown"].items():
            print(f"  {n:>3}건  {err}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean


FRONTEND_EVENT = "frontend_latency_turn"
BACKEND_EVENT = "backend_latency_turn"

CSV_COLUMNS = [
    "session_id",
    "request_id",
    "turn_index",
    "frontend_stt_processing_ms",
    "api_round_trip_ms",
    "agent_processing_ms",
    "frontend_tts_processing_ms",
    "total_response_latency_ms",
]


def extract_json(line: str) -> dict | None:
    start = line.find("{")
    if start < 0:
        return None
    try:
        return json.loads(line[start:])
    except json.JSONDecodeError:
        return None


def load_logs(paths: list[Path]) -> dict[tuple[str, str, int], dict]:
    merged: dict[tuple[str, str, int], dict] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            payload = extract_json(line.strip())
            if not payload:
                continue
            if payload.get("event") not in {FRONTEND_EVENT, BACKEND_EVENT}:
                continue
            key = (
                payload.get("session_id"),
                payload.get("request_id"),
                int(payload.get("turn_index") or 0),
            )
            merged.setdefault(key, {}).update(payload)
    return merged


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in CSV_COLUMNS})


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    grouped: dict[int, dict[str, list[float]]] = {}
    for row in rows:
        turn_index = int(row["turn_index"])
        group = grouped.setdefault(turn_index, {})
        for metric in CSV_COLUMNS[3:]:
            value = row.get(metric)
            if value is None or value == "":
                continue
            group.setdefault(metric, []).append(float(value))

    summary_columns = [
        "turn_index",
        "average_total_response_latency_ms",
        "average_frontend_stt_processing_ms",
        "average_api_round_trip_ms",
        "average_agent_processing_ms",
        "average_frontend_tts_processing_ms",
    ]
    metric_map = {
        "average_total_response_latency_ms": "total_response_latency_ms",
        "average_frontend_stt_processing_ms": "frontend_stt_processing_ms",
        "average_api_round_trip_ms": "api_round_trip_ms",
        "average_agent_processing_ms": "agent_processing_ms",
        "average_frontend_tts_processing_ms": "frontend_tts_processing_ms",
    }

    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=summary_columns)
        writer.writeheader()
        for turn_index in sorted(grouped):
            group = grouped[turn_index]
            row = {"turn_index": turn_index}
            for summary_key, raw_key in metric_map.items():
                values = group.get(raw_key, [])
                row[summary_key] = round(mean(values), 2) if values else ""
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Console log files containing frontend/backend JSON latency logs",
    )
    parser.add_argument(
        "--out",
        default="latency_turns.csv",
        help="Per-turn merged CSV output path",
    )
    parser.add_argument(
        "--summary-out",
        default="latency_turn_summary.csv",
        help="Averaged summary CSV output path",
    )
    args = parser.parse_args()

    merged = load_logs([Path(value) for value in args.inputs])
    rows = [
        {
            "session_id": session_id,
            "request_id": request_id,
            "turn_index": turn_index,
            **payload,
        }
        for (session_id, request_id, turn_index), payload in sorted(
            merged.items(),
            key=lambda item: (item[0][0], item[0][2], item[0][1]),
        )
    ]

    write_csv(Path(args.out), rows)
    write_summary_csv(Path(args.summary_out), rows)


if __name__ == "__main__":
    main()

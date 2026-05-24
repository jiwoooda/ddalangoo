#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean


LATENCY_MARKER = "[LATENCY]"
TARGET_EVENT = "frontend_latency_turn"

TURN_COLUMNS = [
    "variant",
    "session_id",
    "request_id",
    "turn_index",
    "response_text_length",
    "frontend_stt_processing_ms",
    "api_round_trip_ms",
    "frontend_tts_processing_ms",
    "speech_to_voice_ms",
    "total_response_latency_ms",
    "total_interaction_latency_ms",
]

SUMMARY_COLUMNS = [
    "variant",
    "turn_count",
    "avg_speech_to_voice_ms",
    "avg_frontend_stt_processing_ms",
    "avg_api_round_trip_ms",
    "avg_frontend_tts_processing_ms",
    "avg_total_interaction_latency_ms",
]


def extract_latency_payloads(text: str) -> list[dict]:
    # Flutter debugPrint는 [LATENCY] 다음 줄부터 들여쓰기 JSON을 여러 줄로 찍는다.
    # JSONDecoder.raw_decode를 쓰면 JSON 끝 위치를 직접 찾을 수 있어 중간 일반 로그를 건너뛸 수 있다.
    decoder = json.JSONDecoder()
    payloads: list[dict] = []
    search_from = 0

    while True:
        marker_index = text.find(LATENCY_MARKER, search_from)
        if marker_index < 0:
            break

        json_start = text.find("{", marker_index)
        if json_start < 0:
            break

        try:
            payload, json_end = decoder.raw_decode(text[json_start:])
        except json.JSONDecodeError:
            search_from = marker_index + len(LATENCY_MARKER)
            continue

        if isinstance(payload, dict):
            payloads.append(payload)
        search_from = json_start + json_end

    return payloads


def load_turn_rows(paths: list[Path], variant: str) -> list[dict]:
    rows: list[dict] = []

    for path in paths:
        for payload in extract_latency_payloads(path.read_text(encoding="utf-8")):
            if payload.get("event") != TARGET_EVENT:
                continue

            # 발표에서는 user_speech_end -> audio_play_start가 핵심 체감 지표다.
            # 기존 logger의 total_response_latency_ms와 같은 값이지만 이름을 명확히 한 번 더 둔다.
            speech_to_voice_ms = payload.get("total_response_latency_ms")
            row = {
                "variant": variant,
                "speech_to_voice_ms": speech_to_voice_ms,
                **payload,
            }
            rows.append(row)

    return rows


def numeric_values(rows: list[dict], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None or value == "":
            continue
        values.append(float(value))
    return values


def average(rows: list[dict], key: str) -> float | str:
    values = numeric_values(rows, key)
    return round(mean(values), 2) if values else ""


def write_turn_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=TURN_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in TURN_COLUMNS})


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    variants = sorted({row["variant"] for row in rows})

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()

        for variant in variants:
            variant_rows = [row for row in rows if row["variant"] == variant]
            writer.writerow(
                {
                    "variant": variant,
                    "turn_count": len(variant_rows),
                    "avg_speech_to_voice_ms": average(
                        variant_rows,
                        "speech_to_voice_ms",
                    ),
                    "avg_frontend_stt_processing_ms": average(
                        variant_rows,
                        "frontend_stt_processing_ms",
                    ),
                    "avg_api_round_trip_ms": average(
                        variant_rows,
                        "api_round_trip_ms",
                    ),
                    "avg_frontend_tts_processing_ms": average(
                        variant_rows,
                        "frontend_tts_processing_ms",
                    ),
                    "avg_total_interaction_latency_ms": average(
                        variant_rows,
                        "total_interaction_latency_ms",
                    ),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Flutter [LATENCY] console logs into CSV files.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Flutter console log files saved from AS-IS or TO-BE runs.",
    )
    parser.add_argument(
        "--variant",
        required=True,
        help="Label for these logs, for example AS_IS_BACKEND_STT_TTS or TO_BE_FRONTEND_STT_TTS.",
    )
    parser.add_argument("--out", default="latency_turns.csv")
    parser.add_argument("--summary-out", default="latency_summary.csv")
    args = parser.parse_args()

    rows = load_turn_rows([Path(input_path) for input_path in args.inputs], args.variant)
    write_turn_csv(Path(args.out), rows)
    write_summary_csv(Path(args.summary_out), rows)

    print(f"parsed_turns={len(rows)}")
    print(f"turn_csv={args.out}")
    print(f"summary_csv={args.summary_out}")


if __name__ == "__main__":
    main()

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOG_DIR = _REPO_ROOT / "stt_tts_latency_test"
_FRONTEND_VOICE_TIMELINE_LOG = _LOG_DIR / "frontend_voice_timeline.jsonl"
_FRONTEND_LATENCY_TURN_LOG = _LOG_DIR / "frontend_latency_turns.jsonl"
_BACKEND_VOICE_TIMELINE_LOG = _LOG_DIR / "backend_voice_timeline.jsonl"
_FRONTEND_INGEST_PATHS = {
    "frontend_voice_timeline.jsonl": _FRONTEND_VOICE_TIMELINE_LOG,
    "frontend_latency_turns.jsonl": _FRONTEND_LATENCY_TURN_LOG,
}
_DASHBOARD_HTML_PATH = (
    Path(__file__).resolve().parents[1]
    / "static"
    / "voice_timeline_dashboard"
    / "index.html"
)
_MAX_RECORDS_PER_FILE = 5000


def get_dashboard_html_path() -> Path:
    return _DASHBOARD_HTML_PATH


def append_frontend_log_line(file_name: str, json_line: str) -> Path:
    path = _FRONTEND_INGEST_PATHS.get(file_name)
    if path is None:
        raise ValueError(f"unsupported frontend log file: {file_name}")

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json_line.rstrip("\n"))
        handle.write("\n")
    return path


def get_voice_timeline_dashboard_data(
    *,
    event_limit: int = 300,
    turn_limit: int = 120,
) -> dict[str, Any]:
    frontend_events = _read_jsonl(
        _FRONTEND_VOICE_TIMELINE_LOG,
        max_records=_MAX_RECORDS_PER_FILE,
    )
    backend_events = _read_jsonl(
        _BACKEND_VOICE_TIMELINE_LOG,
        max_records=_MAX_RECORDS_PER_FILE,
    )
    latency_turns = _read_jsonl(
        _FRONTEND_LATENCY_TURN_LOG,
        max_records=_MAX_RECORDS_PER_FILE,
    )

    recent_turns = _build_recent_turns(latency_turns, limit=turn_limit)
    recent_events = _build_recent_events(
        frontend_events=frontend_events,
        backend_events=backend_events,
        latency_turns=latency_turns,
        limit=event_limit,
    )
    request_summaries = _build_request_summaries(recent_events)

    return {
        "generatedAt": _iso_now(),
        "files": {
            "frontendVoiceTimeline": _file_info(
                _FRONTEND_VOICE_TIMELINE_LOG,
                parsed_count=len(frontend_events),
            ),
            "frontendLatencyTurns": _file_info(
                _FRONTEND_LATENCY_TURN_LOG,
                parsed_count=len(latency_turns),
            ),
            "backendVoiceTimeline": _file_info(
                _BACKEND_VOICE_TIMELINE_LOG,
                parsed_count=len(backend_events),
            ),
        },
        "summary": _build_summary(
            frontend_events=frontend_events,
            backend_events=backend_events,
            latency_turns=latency_turns,
        ),
        "requestSummaries": request_summaries,
        "recentTurns": recent_turns,
        "recentEvents": recent_events,
    }


def _read_jsonl(path: Path, *, max_records: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: deque[dict[str, Any]] = deque(maxlen=max_records)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
    except OSError:
        return []

    return list(records)


def _file_info(path: Path, *, parsed_count: int) -> dict[str, Any]:
    exists = path.exists()
    stat = path.stat() if exists else None
    return {
        "path": str(path),
        "exists": exists,
        "parsedCount": parsed_count,
        "sizeBytes": stat.st_size if stat else 0,
        "modifiedAt": _iso_from_timestamp(stat.st_mtime) if stat else None,
    }


def _build_summary(
    *,
    frontend_events: list[dict[str, Any]],
    backend_events: list[dict[str, Any]],
    latency_turns: list[dict[str, Any]],
) -> dict[str, Any]:
    native_asr_completed = [
        event for event in frontend_events if event.get("event") == "native_asr_completed"
    ]
    backend_tts_events = [
        event for event in backend_events if event.get("backendTtsBuildMs") is not None
    ]
    event_counts = Counter(
        event.get("event", "unknown") for event in frontend_events + backend_events
    )

    return {
        "frontendVoiceEventCount": len(frontend_events),
        "backendVoiceEventCount": len(backend_events),
        "latencyTurnCount": len(latency_turns),
        "nativeAsrCompletionCount": len(native_asr_completed),
        "backendTtsBuildCount": len(backend_tts_events),
        "topEvents": dict(event_counts.most_common(8)),
        "totalResponseLatencyMs": _metric_summary(
            turn.get("total_response_latency_ms") for turn in latency_turns
        ),
        "frontendSttProcessingMs": _metric_summary(
            turn.get("frontend_stt_processing_ms") for turn in latency_turns
        ),
        "apiRoundTripMs": _metric_summary(
            turn.get("api_round_trip_ms") for turn in latency_turns
        ),
        "backendTtsRoundTripMs": _metric_summary(
            turn.get("backend_tts_round_trip_ms") for turn in latency_turns
        ),
        "nativeAsrListenToFinalMs": _metric_summary(
            _nested_get(event, "durationsMs", "listen_to_final_result_event")
            for event in native_asr_completed
        ),
        "nativeAsrStopToResolvedMs": _metric_summary(
            _nested_get(event, "durationsMs", "stop_to_result_resolved")
            for event in native_asr_completed
        ),
        "backendTtsBuildMs": _metric_summary(
            event.get("backendTtsBuildMs") for event in backend_tts_events
        ),
        "agentResponseTtsBuildMs": _metric_summary(
            event.get("backendTtsBuildMs")
            for event in backend_tts_events
            if event.get("route") == "agent_response"
        ),
        "directTtsBuildMs": _metric_summary(
            event.get("backendTtsBuildMs")
            for event in backend_tts_events
            if event.get("route") == "voice_tts"
        ),
        "latestTimestamp": _latest_timestamp(
            [
                _sort_timestamp(event)
                for event in frontend_events + backend_events + latency_turns
            ]
        ),
    }


def _metric_summary(values: Any) -> dict[str, Any] | None:
    numbers = [float(value) for value in values if isinstance(value, (int, float))]
    if not numbers:
        return None

    ordered = sorted(numbers)
    return {
        "count": len(ordered),
        "avg": round(sum(ordered) / len(ordered), 1),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "min": round(ordered[0], 1),
        "max": round(ordered[-1], 1),
    }


def _percentile(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(len(sorted_values) * ratio) - 1)
    return round(sorted_values[index], 1)


def _build_recent_turns(
    latency_turns: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    normalized = []
    for turn in latency_turns:
        normalized.append(
            {
                "sortAt": _sort_timestamp(turn),
                "requestId": turn.get("request_id"),
                "sessionId": turn.get("session_id"),
                "turnIndex": turn.get("turn_index"),
                "mode": turn.get("mode"),
                "totalResponseLatencyMs": turn.get("total_response_latency_ms"),
                "frontendSttProcessingMs": turn.get("frontend_stt_processing_ms"),
                "apiRoundTripMs": turn.get("api_round_trip_ms"),
                "backendTtsRoundTripMs": turn.get("backend_tts_round_trip_ms"),
                "ttsToPlaybackMs": turn.get("tts_to_playback_ms"),
                "audioPlayStart": turn.get("audio_play_start"),
                "audioPlayEnd": turn.get("audio_play_end"),
                "raw": turn,
            }
        )
    normalized.sort(key=lambda item: item["sortAt"] or "", reverse=True)
    return normalized[:limit]


def _build_recent_events(
    *,
    frontend_events: list[dict[str, Any]],
    backend_events: list[dict[str, Any]],
    latency_turns: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for event in frontend_events:
        backend_timeline = event.get("backendVoiceTimeline")
        merged.append(
            {
                "source": "frontend_voice",
                "event": event.get("event", "unknown"),
                "requestId": event.get("requestId")
                or (
                    backend_timeline.get("requestId")
                    if isinstance(backend_timeline, dict)
                    else None
                ),
                "route": (
                    backend_timeline.get("route")
                    if isinstance(backend_timeline, dict)
                    else None
                ),
                "sortAt": _sort_timestamp(event),
                "details": _event_details(event),
                "raw": event,
            }
        )

    for event in backend_events:
        merged.append(
            {
                "source": "backend_voice",
                "event": event.get("event", "backend_voice_timeline"),
                "requestId": event.get("requestId"),
                "route": event.get("route"),
                "sortAt": _sort_timestamp(event),
                "details": _event_details(event),
                "raw": event,
            }
        )

    for turn in latency_turns:
        merged.append(
            {
                "source": "latency_turn",
                "event": turn.get("event", "frontend_latency_turn"),
                "requestId": turn.get("request_id"),
                "route": None,
                "sortAt": _sort_timestamp(turn),
                "details": _event_details(turn),
                "raw": turn,
            }
        )

    merged.sort(key=lambda item: item["sortAt"] or "", reverse=True)
    return merged[:limit]


def _build_request_summaries(
    recent_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in recent_events:
        request_id = str(event.get("requestId") or "").strip()
        if not request_id:
            continue

        summary = grouped.setdefault(
            request_id,
            {
                "requestId": request_id,
                "firstSeenAt": event.get("sortAt"),
                "lastSeenAt": event.get("sortAt"),
                "lastEvent": event.get("event"),
                "route": event.get("route"),
                "sources": set(),
                "eventCount": 0,
            },
        )
        summary["eventCount"] += 1
        summary["sources"].add(event.get("source"))
        first_seen = summary.get("firstSeenAt")
        last_seen = summary.get("lastSeenAt")
        current_seen = event.get("sortAt")
        if current_seen and (not first_seen or current_seen < first_seen):
            summary["firstSeenAt"] = current_seen
        if current_seen and (not last_seen or current_seen > last_seen):
            summary["lastSeenAt"] = current_seen
            summary["lastEvent"] = event.get("event")
        if not summary.get("route") and event.get("route"):
            summary["route"] = event.get("route")

        details = event.get("details") or {}
        _copy_if_present(
            details,
            summary,
            {
                "totalResponseLatencyMs": "totalResponseLatencyMs",
                "frontendSttProcessingMs": "frontendSttProcessingMs",
                "apiRoundTripMs": "apiRoundTripMs",
                "backendTtsRoundTripMs": "backendTtsRoundTripMs",
                "listenToFinalResultMs": "nativeAsrListenToFinalMs",
                "backendTtsBuildMs": "backendTtsBuildMs",
                "responseStage": "responseStage",
                "resolution": "resolution",
                "speechSegmentCount": "speechSegmentCount",
            },
        )

    summaries = []
    for summary in grouped.values():
        summaries.append(
            {
                **summary,
                "sources": sorted(source for source in summary["sources"] if source),
            }
        )
    summaries.sort(key=lambda item: item.get("lastSeenAt") or "", reverse=True)
    return summaries[:80]


def _copy_if_present(
    source: dict[str, Any],
    target: dict[str, Any],
    field_map: dict[str, str],
) -> None:
    for from_key, to_key in field_map.items():
        value = source.get(from_key)
        if value is not None and to_key not in target:
            target[to_key] = value


def _event_details(record: dict[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {}

    for key in (
        "responseStage",
        "responseStatus",
        "speechSegmentCount",
        "partialCount",
        "recoverableErrorCount",
        "resolution",
        "route",
        "timelineLabel",
        "segmentCount",
        "backendTtsBuildMs",
        "assistantMessageLength",
        "textLength",
    ):
        if key in record and record[key] is not None:
            details[key] = record[key]

    if isinstance(record.get("durationsMs"), dict):
        durations = record["durationsMs"]
        _copy_if_present(
            durations,
            details,
            {
                "listen_to_final_result_event": "listenToFinalResultMs",
                "stop_to_result_resolved": "stopToResultResolvedMs",
                "speech_begin_to_final_result_event": "speechBeginToFinalResultMs",
            },
        )

    if isinstance(record.get("backendVoiceTimeline"), dict):
        backend_timeline = record["backendVoiceTimeline"]
        _copy_if_present(
            backend_timeline,
            details,
            {
                "route": "route",
                "segmentCount": "segmentCount",
                "backendTtsBuildMs": "backendTtsBuildMs",
            },
        )

    if "total_response_latency_ms" in record:
        _copy_if_present(
            record,
            details,
            {
                "total_response_latency_ms": "totalResponseLatencyMs",
                "frontend_stt_processing_ms": "frontendSttProcessingMs",
                "api_round_trip_ms": "apiRoundTripMs",
                "backend_tts_round_trip_ms": "backendTtsRoundTripMs",
            },
        )

    return details


def _nested_get(record: dict[str, Any], *keys: str) -> Any:
    current: Any = record
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _sort_timestamp(record: dict[str, Any]) -> str | None:
    for key in (
        "loggedAt",
        "audio_play_end",
        "audio_play_start",
        "resultResolvedAt",
        "backendResponseReadyAt",
        "backendTtsBuildCompletedAt",
        "createdAt",
        "interaction_start",
    ):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _latest_timestamp(values: list[str | None]) -> str | None:
    filtered = [value for value in values if value]
    if not filtered:
        return None
    return max(filtered)


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()

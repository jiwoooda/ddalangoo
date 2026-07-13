"""OpenAI STT + Gemini TTS 기반 음성 서비스.

업로드된 오디오 파일은 OpenAI Transcription API로 전사하고,
응답 TTS는 기존 Gemini TTS를 사용한다.

API Key는 환경변수 OPENAI_API_KEY / GEMINI_API_KEY에서 읽는다.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import json
import os
import re
import logging
import base64
import hashlib
import shutil
import struct
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from google import genai
from google.genai import types
from openai import AsyncOpenAI
from fastapi import HTTPException
from app.schemas.voice import TtsSegment, TurnDetectionRequest, TurnDetectionResponse
from app.schemas.agent import SpeechSegment

logger = logging.getLogger(__name__)

# ── 모델 / 프롬프트 ─────────────────────────────────────────────────────────

# 프론트는 녹음이 끝난 WAV 파일을 업로드한다. 진짜 Realtime 스트리밍은
# WebRTC/WebSocket 입력 구조가 필요하므로, 현재 엔드포인트에서는 Transcription API를 사용한다.
_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
_TURN_DETECTION_MODEL = os.getenv("TURN_DETECTION_MODEL", "gpt-4.1-mini")
_TURN_DETECTION_TIMEOUT_SECONDS = float(os.getenv("TURN_DETECTION_TIMEOUT_SECONDS", "3.0"))
_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
_TTS_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv(
        "GEMINI_TTS_FALLBACK_MODELS",
        "gemini-3.1-flash-tts-preview",
    ).split(",")
    if model.strip()
]
_TTS_VOICE = os.getenv("GEMINI_TTS_VOICE", "Zephyr")
_TTS_SAMPLE_RATE = 24000

# 쇼핑 도메인 표현 정확도를 높이기 위한 STT 프롬프트.
_STT_PROMPT = (
    "너는 한국어 음성 인식 엔진이다. "
    "오디오에서 실제로 들리는 사용자의 말만 한 줄 한국어 텍스트로 전사해라. "
    "오디오에 없는 문장, 대화 예시, 답변, 설명은 절대 만들지 마라. "
    "상품명, 수량, 가격, 배송지, 장바구니, 결제, 재주문과 관련된 표현은 특히 정확히 전사해라. "
    "말이 불명확하거나 배경음/무음이면 빈 문자열만 출력해라. "
    "줄바꿈 없이 텍스트만 출력해라."
)

_MAX_TRANSCRIPT_LENGTH = 200
_MAX_TURN_TEXT_LENGTH = 500
_MIN_AUDIO_BYTES = 1000  # 너무 작은 파일은 무음으로 간주
_MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MB
_MAX_TTS_TEXT_LENGTH = 1000
_STATIC_TTS_ROOT = Path(__file__).resolve().parents[1] / "static" / "tts"
_LEGACY_STATIC_TTS_ROOT = Path(__file__).resolve().parents[2] / "static" / "tts"
_TTS_CACHE_DIRNAME = "cache"
_DYNAMIC_TTS_TTL_SECONDS = int(os.getenv("DYNAMIC_TTS_TTL_SECONDS", str(6 * 60 * 60)))
_CACHED_TTS_TTL_SECONDS = int(
    os.getenv("CACHED_TTS_TTL_SECONDS", str(10 * 365 * 24 * 60 * 60))
)


@dataclass
class _SynthesizedTtsSegment:
    text: str
    wav_bytes: bytes
    duration_ms: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_voice_timeline(
    *,
    request_id: str,
    route: str,
    conversation_id: int | None = None,
    text_length: int | None = None,
) -> dict[str, Any]:
    timeline: dict[str, Any] = {
        "requestId": request_id,
        "route": route,
        "createdAt": _utc_now_iso(),
    }
    if conversation_id is not None:
        timeline["conversationId"] = conversation_id
    if text_length is not None:
        timeline["textLength"] = text_length
    return timeline


def mark_voice_timeline(timeline: dict[str, Any] | None, key: str) -> str | None:
    if timeline is None:
        return None
    stamped = _utc_now_iso()
    timeline[key] = stamped
    return stamped


def log_voice_timeline(label: str, timeline: dict[str, Any] | None) -> None:
    if not timeline:
        return
    logger.info(
        "[voice.timeline.%s] %s",
        label,
        json.dumps(timeline, ensure_ascii=False, default=str),
    )


def _set_voice_timeline_value(
    timeline: dict[str, Any] | None,
    key: str,
    value: Any,
) -> None:
    if timeline is None or value is None:
        return
    timeline[key] = value


def _mark_first_audio_ready(timeline: dict[str, Any] | None) -> None:
    if timeline is None or timeline.get("ttsFirstAudioReadyAt"):
        return
    mark_voice_timeline(timeline, "ttsFirstAudioReadyAt")


def _update_segment_timing(
    timeline: dict[str, Any] | None,
    index: int,
    **fields: Any,
) -> None:
    if timeline is None or index < 0:
        return
    timings = timeline.setdefault("segmentTimings", [])
    while len(timings) <= index:
        timings.append({"index": len(timings)})
    segment = timings[index]
    for key, value in fields.items():
        if value is not None:
            segment[key] = value


def _get_openai_client(feature: str = "stt") -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "")
    logger.info("[voice.%s] OPENAI_API_KEY exists: %s", feature, bool(api_key))
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": f"{feature.upper()}_CONFIG_ERROR",
                    "message": f"{feature.upper()} 서비스가 설정되지 않았습니다.",
                }
            },
        )
    return AsyncOpenAI(api_key=api_key)


def _get_client(feature: str = "stt") -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "")
    logger.info("[voice.%s] GEMINI_API_KEY exists: %s", feature, bool(api_key))
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": f"{feature.upper()}_CONFIG_ERROR",
                    "message": f"{feature.upper()} 서비스가 설정되지 않았습니다.",
                }
            },
        )
    return genai.Client(api_key=api_key)


async def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """오디오 바이트를 OpenAI Transcription API로 전사해 텍스트를 반환한다.

    빈 발화이면 빈 문자열("")을 반환한다.
    오류 시 HTTPException을 발생시킨다.
    """
    if len(audio_bytes) < _MIN_AUDIO_BYTES:
        logger.info(
            "[voice.stt] audio too small; returning empty transcript size=%s",
            len(audio_bytes),
        )
        return ""

    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "code": "AUDIO_TOO_LARGE",
                    "message": "오디오 파일이 너무 큽니다. 20MB 이하로 전송해주세요.",
                }
            },
        )

    safe_mime = _normalize_openai_audio_mime(mime_type)
    filename = _filename_for_mime(safe_mime)
    logger.info(
        "[voice.stt] OpenAI STT request started model=%s mime_type=%s size=%s",
        _STT_MODEL,
        safe_mime,
        len(audio_bytes),
    )

    try:
        client = _get_openai_client("stt")
        # OpenAI SDK는 파일명 확장자를 함께 보므로 BytesIO에 name을 지정한다.
        audio_file = BytesIO(audio_bytes)
        audio_file.name = filename

        response = await client.audio.transcriptions.create(
            model=_STT_MODEL,
            file=(filename, audio_file, safe_mime),
            language="ko",
            prompt=_STT_PROMPT,
        )
        raw = (getattr(response, "text", "") or "").strip()
        transcript = _normalize_transcript(raw)
        logger.info(
            "[voice.stt] OpenAI STT succeeded raw_length=%s transcript_length=%s",
            len(raw),
            len(transcript),
        )
        return transcript

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[voice.stt] OpenAI STT failed")
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "STT_API_ERROR",
                    "message": f"음성 인식 중 오류가 발생했습니다: {exc}",
                }
            },
        ) from exc


async def detect_turn_completion(req: TurnDetectionRequest) -> TurnDetectionResponse:
    """STT 결과가 의미상 한 사용자 턴으로 완성됐는지 LLM으로 판단한다.

    LLM 호출 실패, timeout, JSON parse 실패 시 rule-based fallback을 사용한다.
    """
    transcript = _normalize_turn_text(req.transcript)
    partial = _normalize_turn_text(req.partialTranscript or "")
    step = (req.step or "").strip() or "unknown"
    merged = _merge_turn_transcripts(partial, transcript)

    fallback = _detect_turn_rule_based(
        transcript=transcript,
        partial=partial,
        merged=merged,
        step=step,
        continuation_count=req.continuationCount,
    )
    if not transcript:
        return fallback

    try:
        return await asyncio.wait_for(
            _detect_turn_completion_with_llm(
                transcript=transcript,
                partial=partial,
                merged=merged,
                step=step,
                continuation_count=req.continuationCount,
            ),
            timeout=_TURN_DETECTION_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "[voice.turn_detection] fallback reason=%s step=%s transcript=%s partial=%s",
            exc,
            step,
            transcript,
            partial,
        )
        return fallback


async def _detect_turn_completion_with_llm(
    *,
    transcript: str,
    partial: str,
    merged: str,
    step: str,
    continuation_count: int,
) -> TurnDetectionResponse:
    client = _get_openai_client("turn_detection")
    response = await client.chat.completions.create(
        model=_TURN_DETECTION_MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "너는 한국어 음성 쇼핑 앱의 turn detector다. "
                    "STT transcript가 사용자의 의미상 한 턴으로 완성됐는지 판단한다. "
                    "VAD는 소리의 끝만 판단하므로, 너는 의미 완성 여부만 판단한다. "
                    "특히 askProduct 단계에서는 검색어 후보가 잡히면 문장이 조금 덜 끝났더라도 complete로 본다. "
                    "반드시 JSON schema에 맞춰 답한다."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "currentStep": step,
                        "partialTranscript": partial,
                        "newTranscript": transcript,
                        "mergedTranscript": merged,
                        "continuationCount": continuation_count,
                        "resultOptions": ["complete", "incomplete", "noise_or_empty"],
                        "rules": [
                            "상품명/수량/긍정/부정/결제/삭제/변경 의도가 명확하면 complete",
                            "askProduct 단계에서는 상품 검색어 후보(예: 토마토, 맛있는 토마토)가 잡히면 문장 끝이 조금 끊겨도 complete",
                            "말이 끊긴 filler나 접속어만 있으면 incomplete 또는 noise_or_empty",
                            "mergedTranscript가 너무 모호하고 추가 발화가 필요하면 incomplete",
                            "무음, 감탄사, 의미 없는 한 글자 발화는 noise_or_empty",
                            "현재 단계에 맞는 짧은 답변(응, 네, 아니, 2개, 결제할게)은 complete",
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "turn_detection_result",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "result": {
                            "type": "string",
                            "enum": ["complete", "incomplete", "noise_or_empty"],
                        },
                        "mergedTranscript": {"type": "string"},
                        "reason": {"type": "string"},
                        "shouldAskClarification": {"type": "boolean"},
                    },
                    "required": [
                        "result",
                        "mergedTranscript",
                        "reason",
                        "shouldAskClarification",
                    ],
                },
            },
        },
    )
    content = response.choices[0].message.content or ""
    data = json.loads(content)
    result = str(data.get("result") or "").strip()
    if result not in {"complete", "incomplete", "noise_or_empty"}:
        raise ValueError(f"invalid turn detection result: {result}")
    merged_transcript = _normalize_turn_text(data.get("mergedTranscript") or merged)
    if (
        result == "incomplete"
        and step == "askProduct"
        and _looks_like_product_search_fragment(merged_transcript)
    ):
        return TurnDetectionResponse(
            result="complete",
            mergedTranscript=merged_transcript,
            reason="llm_override_product_search_fragment",
            shouldAskClarification=False,
        )
    return TurnDetectionResponse(
        result=result,
        mergedTranscript=merged_transcript,
        reason=str(data.get("reason") or "llm").strip(),
        shouldAskClarification=bool(data.get("shouldAskClarification")),
    )


def _detect_turn_rule_based(
    *,
    transcript: str,
    partial: str,
    merged: str,
    step: str,
    continuation_count: int,
) -> TurnDetectionResponse:
    compact = re.sub(r"\s+", "", merged)
    new_compact = re.sub(r"\s+", "", transcript)
    if (
        not compact
        or len(compact) < 2
        or (compact in {"음", "어", "아", "네", "응"} and step == "askProduct")
    ):
        return TurnDetectionResponse(
            result="noise_or_empty",
            mergedTranscript=merged,
            reason="rule_noise_or_empty",
            shouldAskClarification=bool(partial and continuation_count >= 1),
        )

    complete_markers = (
        "사줘",
        "찾아줘",
        "담아",
        "담아줘",
        "결제",
        "주문",
        "빼줘",
        "삭제",
        "바꿔",
        "변경",
        "아니",
        "싫어",
        "좋아",
        "맞아",
    )
    quantity_pattern = re.compile(
        r"\d+\s*(개|봉지|팩|세트|통|병|캔)|한\s*개|두\s*개|세\s*개|네\s*개|다섯\s*개"
    )
    confirmation_steps = {
        "showProduct",
        "askQuantity",
        "askMoreOrCheckout",
        "confirmAddress",
        "enterPassword",
    }
    if (
        any(marker in compact for marker in complete_markers)
        or quantity_pattern.search(merged)
        or (step in confirmation_steps and new_compact in {"응", "네", "예", "그래", "좋아", "아니"})
        or (step == "askProduct" and len(compact) >= 3 and continuation_count > 0)
        or (step == "askProduct" and _looks_like_product_search_fragment(merged))
    ):
        return TurnDetectionResponse(
            result="complete",
            mergedTranscript=merged,
            reason="rule_complete",
            shouldAskClarification=False,
        )

    if continuation_count >= 2:
        return TurnDetectionResponse(
            result="incomplete",
            mergedTranscript=merged,
            reason="rule_max_continuation",
            shouldAskClarification=True,
        )

    return TurnDetectionResponse(
        result="incomplete",
        mergedTranscript=merged,
        reason="rule_incomplete",
        shouldAskClarification=False,
    )


def _normalize_turn_text(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())[:_MAX_TURN_TEXT_LENGTH]


def _merge_turn_transcripts(partial: str, transcript: str) -> str:
    if partial and transcript:
        return _normalize_turn_text(f"{partial} {transcript}")
    return _normalize_turn_text(partial or transcript)


def _looks_like_product_search_fragment(text: str) -> bool:
    normalized = _normalize_turn_text(text)
    if not normalized:
        return False

    compact = re.sub(r"\s+", "", normalized)
    if compact in {"음", "어", "아", "저기", "그", "그거", "이거", "그냥"}:
        return False

    stripped = re.sub(r"[.!?~…]+$", "", normalized).strip()
    stripped = re.sub(
        r"(사고싶어|사고싶은|사줘|사|찾아줘|찾아|찾|추천해줘|추천|보여줘|보여|줘|좀)$",
        "",
        stripped,
    ).strip()
    tokens = [
        token
        for token in re.findall(r"[0-9A-Za-z가-힣]+", stripped)
        if len(token) >= 2
    ]
    return bool(tokens)


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _normalize_openai_audio_mime(mime_type: str) -> str:
    """OpenAI Transcription API가 받는 오디오 MIME 타입으로 정규화한다."""
    mime = (mime_type or "").lower().split(";")[0].strip()
    _supported = {
        "audio/wav", "audio/wave", "audio/x-wav",
        "audio/mp4", "audio/mpeg", "audio/mp3",
        "audio/mpga", "audio/webm", "audio/x-m4a",
    }
    if mime in _supported:
        if mime in {"audio/wave", "audio/x-wav"}:
            return "audio/wav"
        if mime == "audio/mp3":
            return "audio/mpeg"
        if mime == "audio/x-m4a":
            return "audio/mp4"
        return mime

    if "wav" in mime:
        return "audio/wav"
    if "mp3" in mime or "mpeg" in mime or "mpga" in mime:
        return "audio/mpeg"
    if "webm" in mime:
        return "audio/webm"
    if "m4a" in mime or "aac" in mime or "mp4" in mime:
        return "audio/mp4"

    # 현재 프론트 녹음은 WAV이므로 알 수 없는 타입은 WAV로 취급한다.
    return "audio/wav"


def _filename_for_mime(mime_type: str) -> str:
    """Transcription API에 넘길 파일명 확장자를 MIME 타입에 맞춘다."""
    extension_by_mime = {
        "audio/wav": "wav",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/mpga": "mpga",
        "audio/webm": "webm",
    }
    extension = extension_by_mime.get(mime_type, "wav")
    return f"speech.{extension}"


def _normalize_transcript(raw: str) -> str:
    """Gemini가 반환한 텍스트를 정제한다.

    - 여러 줄이면 한 줄로 이어 붙인다
    - 앞뒤 인용부호 제거
    - 너무 긴 텍스트는 빈 문자열로 처리
    """
    if not raw:
        return ""

    lines = [l.strip() for l in re.split(r"[\r\n]+", raw) if l.strip()]
    if not lines:
        return ""

    text = " ".join(lines)

    # 앞뒤 인용부호 제거
    quotes = ('"', "'", "“", "”", "‘", "’")
    while text and text[0] in quotes:
        text = text[1:].lstrip()
    while text and text[-1] in quotes:
        text = text[:-1].rstrip()

    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > _MAX_TRANSCRIPT_LENGTH:
        return ""

    return text


async def synthesize_speech(
    text: str,
    *,
    timeline: dict[str, Any] | None = None,
) -> bytes:
    """텍스트를 Gemini TTS로 합성하고 WAV bytes를 반환한다."""
    audio_bytes, _, _ = await synthesize_speech_bundle(text, timeline=timeline)
    return audio_bytes


async def synthesize_speech_bundle(
    text: str,
    *,
    timeline: dict[str, Any] | None = None,
) -> tuple[bytes, list[TtsSegment], int]:
    """텍스트를 내부적으로 문장 분리해 하나의 WAV와 문장 메타데이터로 반환한다."""
    normalized = text.strip()
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_TEXT",
                    "message": "TTS로 읽을 텍스트가 비어 있습니다.",
                }
            },
        )
    if len(normalized) > _MAX_TTS_TEXT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "code": "TEXT_TOO_LONG",
                    "message": "TTS 텍스트가 너무 깁니다.",
                }
            },
        )

    sentences = _split_tts_sentences(normalized)
    build_started_at = time.perf_counter()
    mark_voice_timeline(timeline, "backendTtsBuildStartedAt")
    _set_voice_timeline_value(timeline, "segmentCount", len(sentences))

    async def _synth(index: int, sentence: str) -> _SynthesizedTtsSegment:
        wav_bytes = await _synthesize_sentence_wav(
            sentence,
            timeline=timeline,
            segment_index=index,
        )
        return _SynthesizedTtsSegment(
            text=sentence,
            wav_bytes=wav_bytes,
            duration_ms=_estimate_wav_duration_ms(wav_bytes),
        )

    synthesized_segments: list[_SynthesizedTtsSegment] = list(
        await asyncio.gather(
            *[_synth(index, sentence) for index, sentence in enumerate(sentences)]
        )
    )

    if len(synthesized_segments) == 1:
        combined_audio = synthesized_segments[0].wav_bytes
    else:
        combined_audio = _concatenate_wav_segments(
            [segment.wav_bytes for segment in synthesized_segments]
        )
    response_segments = [
        TtsSegment(text=segment.text, durationMs=segment.duration_ms)
        for segment in synthesized_segments
    ]
    total_duration_ms = sum(segment.duration_ms for segment in synthesized_segments)
    mark_voice_timeline(timeline, "backendTtsBuildCompletedAt")
    _set_voice_timeline_value(
        timeline,
        "backendTtsBuildMs",
        round((time.perf_counter() - build_started_at) * 1000),
    )
    return combined_audio, response_segments, total_duration_ms


async def _synthesize_sentence_wav(
    normalized: str,
    *,
    timeline: dict[str, Any] | None = None,
    segment_index: int | None = None,
) -> bytes:
    client = _get_client("tts")
    models_to_try = list(dict.fromkeys([_TTS_MODEL, *_TTS_FALLBACK_MODELS]))
    last_error: Exception | None = None
    last_provider_error: dict | None = None
    segment_started_at = time.perf_counter()
    if segment_index is not None:
        _update_segment_timing(
            timeline,
            segment_index,
            text=normalized,
            textLength=len(normalized),
            startedAt=_utc_now_iso(),
        )
    logger.info(
        "[voice.tts] Gemini TTS started model=%s fallback_models=%s voice=%s",
        _TTS_MODEL,
        ",".join(_TTS_FALLBACK_MODELS) or "none",
        _TTS_VOICE,
    )

    for model in models_to_try:
        started_at = time.perf_counter()
        logger.info(
            "[voice.tts] Gemini request started model=%s voice=%s text_length=%s",
            model,
            _TTS_VOICE,
            len(normalized),
        )

        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=_tts_prompt(normalized),
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=_TTS_VOICE,
                            ),
                        ),
                    ),
                ),
            )
            latency_ms = round((time.perf_counter() - started_at) * 1000)
            response_mime_type = _extract_audio_mime_type(response)
            audio_payload = _extract_audio_payload(response)
            logger.info(
                "[voice.tts] response_mime_type=%s latency_ms=%s",
                response_mime_type,
                latency_ms,
            )
            if not audio_payload:
                raise RuntimeError("Gemini TTS 응답에서 오디오 데이터를 받지 못했습니다.")

            wav_bytes = _wrap_pcm16_as_wav(audio_payload)
            _mark_first_audio_ready(timeline)
            if segment_index is not None:
                _update_segment_timing(
                    timeline,
                    segment_index,
                    readyAt=_utc_now_iso(),
                    durationMs=round((time.perf_counter() - segment_started_at) * 1000),
                    audioSize=len(wav_bytes),
                    model=model,
                    cacheHit=False,
                )
            logger.info(
                "[voice.tts] Gemini TTS succeeded model=%s audio_size=%s latency_ms=%s",
                model,
                len(wav_bytes),
                latency_ms,
            )
            return wav_bytes
        except HTTPException:
            raise
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000)
            last_error = exc
            last_provider_error = _provider_error_detail(exc)
            if segment_index is not None:
                _update_segment_timing(
                    timeline,
                    segment_index,
                    lastError=str(exc),
                    model=model,
                )
            logger.warning(
                "[voice.tts] Gemini raw error model=%s status=%s code=%s message=%s latency_ms=%s",
                model,
                last_provider_error.get("provider_status"),
                last_provider_error.get("provider_error_code"),
                last_provider_error.get("provider_message"),
                latency_ms,
            )

    if last_error:
        logger.error(
            "[voice.tts] Gemini TTS failed after all models",
            exc_info=(type(last_error), last_error, last_error.__traceback__),
        )
    raise HTTPException(
        status_code=502,
        detail={
            "error": {
                "code": "TTS_API_ERROR",
                "message": "음성 합성 중 오류가 발생했습니다.",
                **(last_provider_error or {}),
            }
        },
    ) from last_error


def encode_audio_base64(audio_bytes: bytes) -> str:
    """프론트가 JSON으로 받기 쉽게 audio bytes를 base64 문자열로 변환한다."""
    return base64.b64encode(audio_bytes).decode("ascii")


def split_agent_speech_segments(text: str) -> list[str]:
    """Agent assistant message를 TTS 친화적인 문장 단위로 분할한다."""
    normalized = re.sub(r"\s+", " ", str(text or "").replace("\n", " ")).strip()
    if not normalized:
        return []

    sentences = _split_tts_sentences(normalized)
    if not sentences:
        sentences = [normalized]

    segments: list[str] = []
    for sentence in sentences:
        segments.extend(_split_long_tts_segment(sentence))
    return [segment for segment in segments if segment.strip()]


def _split_tts_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if not normalized:
        return []

    sentences: list[str] = []
    start = 0
    for index, char in enumerate(normalized):
        if char not in ".!?。！？":
            continue

        prev_char = normalized[index - 1] if index > 0 else ""
        next_char = normalized[index + 1] if index + 1 < len(normalized) else ""

        # "토마토 1.4kg" 같은 숫자 소수점은 문장 경계로 취급하지 않는다.
        if char == "." and prev_char.isdigit() and next_char.isdigit():
            continue

        sentences.append(normalized[start : index + 1].strip())
        start = index + 1

    if start < len(normalized):
        sentences.append(normalized[start:].strip())

    return [sentence for sentence in sentences if sentence]


async def build_agent_speech_segments(
    text: str,
    *,
    request_id: str | None = None,
    prefer_persistent_cache: bool = False,
    timeline: dict[str, Any] | None = None,
) -> list[SpeechSegment]:
    """Agent assistant text를 문장 단위 speech segment + 접근 가능한 audioUrl로 변환한다."""
    segments = split_agent_speech_segments(text)
    if not segments:
        return []
    build_started_at = time.perf_counter()
    mark_voice_timeline(timeline, "backendTtsBuildStartedAt")
    _set_voice_timeline_value(timeline, "segmentCount", len(segments))
    _set_voice_timeline_value(timeline, "speechSegmentMode", "segmented")

    effective_request_id = request_id or uuid4().hex
    segment_dirs = [
        root / effective_request_id
        for root in dict.fromkeys([_STATIC_TTS_ROOT, _LEGACY_STATIC_TTS_ROOT])
    ]
    for segment_dir in segment_dirs:
        segment_dir.mkdir(parents=True, exist_ok=True)

    cache_dirs = [
        root / _TTS_CACHE_DIRNAME
        for root in dict.fromkeys([_STATIC_TTS_ROOT, _LEGACY_STATIC_TTS_ROOT])
    ]
    if prefer_persistent_cache:
        for cache_dir in cache_dirs:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _segment_retry_texts(segment_text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", segment_text).strip()
        if not normalized:
            return []

        retries: list[str] = [normalized]
        stripped = normalized.rstrip(".!?。！？").strip()
        if stripped and stripped not in retries:
            retries.append(stripped)
        softened = stripped.replace("님", "님 ").strip() if stripped else ""
        if softened and softened not in retries:
            retries.append(softened)
        return retries

    async def _build_combined_fallback_segment() -> list[SpeechSegment]:
        normalized_text = re.sub(r"\s+", " ", text).strip()
        if not normalized_text:
            return []
        _set_voice_timeline_value(timeline, "combinedFallbackUsed", True)

        cache_key = _tts_cache_key(normalized_text) if prefer_persistent_cache else None
        file_name = f"{cache_key}.wav" if cache_key else "combined_fallback.wav"
        target_dirs = cache_dirs if cache_key else segment_dirs
        audio_url = (
            f"/static/tts/{_TTS_CACHE_DIRNAME}/{file_name}"
            if cache_key
            else f"/static/tts/{effective_request_id}/{file_name}"
        )

        if cache_key:
            cached_wav = cache_dirs[0] / file_name
            if cached_wav.exists():
                cached_bytes = await asyncio.to_thread(cached_wav.read_bytes)
                now = time.time()
                await asyncio.gather(
                    *[
                        asyncio.to_thread(os.utime, cache_dir / file_name, (now, now))
                        for cache_dir in cache_dirs
                        if (cache_dir / file_name).exists()
                    ]
                )
                logger.info(
                    "[voice.agent_speech] combined_cache_hit key=%s text=%s",
                    cache_key,
                    normalized_text,
                )
                _mark_first_audio_ready(timeline)
                return [
                    SpeechSegment(
                        index=0,
                        text=normalized_text,
                        audioUrl=audio_url,
                        durationMs=_estimate_wav_duration_ms(cached_bytes),
                    )
                ]

        combined_audio = await synthesize_speech(normalized_text)
        await asyncio.gather(
            *[
                asyncio.to_thread((target_dir / file_name).write_bytes, combined_audio)
                for target_dir in target_dirs
            ]
        )
        _mark_first_audio_ready(timeline)
        logger.info(
            "[voice.agent_speech] combined_fallback_built text=%s size=%s",
            normalized_text,
            len(combined_audio),
        )
        return [
            SpeechSegment(
                index=0,
                text=normalized_text,
                audioUrl=audio_url,
                durationMs=_estimate_wav_duration_ms(combined_audio),
            )
        ]

    async def _build_single_segment(index: int, segment_text: str) -> SpeechSegment:
        retry_texts = _segment_retry_texts(segment_text)
        segment_started_at = time.perf_counter()
        _update_segment_timing(
            timeline,
            index,
            text=segment_text,
            textLength=len(segment_text),
            startedAt=_utc_now_iso(),
        )
        try:
            cache_key = _tts_cache_key(segment_text) if prefer_persistent_cache else None
            if cache_key:
                candidate_cache_keys = [
                    _tts_cache_key(candidate_text)
                    for candidate_text in retry_texts
                ]
                for candidate_index, candidate_cache_key in enumerate(candidate_cache_keys, start=1):
                    cached_wav = cache_dirs[0] / f"{candidate_cache_key}.wav"
                    if not cached_wav.exists():
                        continue
                    cached_bytes = await asyncio.to_thread(cached_wav.read_bytes)
                    now = time.time()
                    await asyncio.gather(
                        *[
                            asyncio.to_thread(os.utime, cache_dir / f"{candidate_cache_key}.wav", (now, now))
                            for cache_dir in cache_dirs
                            if (cache_dir / f"{candidate_cache_key}.wav").exists()
                        ]
                    )
                    logger.info(
                        "[voice.agent_speech] cache_hit key=%s index=%s text=%s candidate_attempt=%s",
                        candidate_cache_key,
                        index,
                        segment_text,
                        candidate_index,
                    )
                    _mark_first_audio_ready(timeline)
                    _update_segment_timing(
                        timeline,
                        index,
                        readyAt=_utc_now_iso(),
                        durationMs=round((time.perf_counter() - segment_started_at) * 1000),
                        audioSize=len(cached_bytes),
                        cacheHit=True,
                        candidateAttempt=candidate_index,
                    )
                    return SpeechSegment(
                        index=index,
                        text=segment_text,
                        audioUrl=f"/static/tts/{_TTS_CACHE_DIRNAME}/{candidate_cache_key}.wav",
                        durationMs=_estimate_wav_duration_ms(cached_bytes),
                    )

            last_error: Exception | None = None
            audio_bytes: bytes | None = None
            used_text = segment_text
            for attempt, retry_text in enumerate(retry_texts, start=1):
                try:
                    logger.info(
                        "[voice.agent_speech] segment_tts_attempt index=%s attempt=%s text=%s",
                        index,
                        attempt,
                        retry_text,
                    )
                    audio_bytes = await synthesize_speech(retry_text)
                    used_text = retry_text
                    if attempt > 1:
                        logger.info(
                            "[voice.agent_speech] segment_tts_retry_succeeded index=%s attempt=%s original_text=%s used_text=%s",
                            index,
                            attempt,
                            segment_text,
                            used_text,
                        )
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "[voice.agent_speech] segment_tts_attempt_failed index=%s attempt=%s original_text=%s retry_text=%s error=%s",
                        index,
                        attempt,
                        segment_text,
                        retry_text,
                        exc,
                    )
                    if attempt < len(retry_texts):
                        await asyncio.sleep(0.18)

            if audio_bytes is None:
                raise last_error or RuntimeError("segment tts returned no audio")

            if cache_key:
                file_name = f"{cache_key}.wav"
                target_dirs = cache_dirs
                audio_url = f"/static/tts/{_TTS_CACHE_DIRNAME}/{file_name}"
            else:
                file_name = f"segment_{index}.wav"
                target_dirs = segment_dirs
                audio_url = f"/static/tts/{effective_request_id}/{file_name}"
            await asyncio.gather(
                *[
                    asyncio.to_thread((target_dir / file_name).write_bytes, audio_bytes)
                    for target_dir in target_dirs
                ]
            )
            _mark_first_audio_ready(timeline)
            _update_segment_timing(
                timeline,
                index,
                readyAt=_utc_now_iso(),
                durationMs=round((time.perf_counter() - segment_started_at) * 1000),
                audioSize=len(audio_bytes),
                cacheHit=False,
                attemptCount=attempt,
                usedText=used_text,
            )
            return SpeechSegment(
                index=index,
                text=segment_text,
                audioUrl=audio_url,
                durationMs=_estimate_wav_duration_ms(audio_bytes),
            )
        except Exception as exc:
            logger.warning(
                "[voice.agent_speech] segment tts failed index=%s text=%s error=%s",
                index,
                segment_text,
                exc,
            )
            _update_segment_timing(
                timeline,
                index,
                failedAt=_utc_now_iso(),
                durationMs=round((time.perf_counter() - segment_started_at) * 1000),
                error=str(exc),
            )
            return SpeechSegment(index=index, text=segment_text, audioUrl=None)

    _sem = asyncio.Semaphore(3)

    async def _limited(index: int, segment_text: str) -> SpeechSegment:
        async with _sem:
            return await _build_single_segment(index, segment_text)

    built_segments = await asyncio.gather(
        *[
            _limited(index, segment_text)
            for index, segment_text in enumerate(segments)
        ]
    )
    missing_audio_segments = [
        segment for segment in built_segments if not segment.audioUrl
    ]
    _set_voice_timeline_value(
        timeline,
        "missingAudioSegmentCount",
        len(missing_audio_segments),
    )
    if timeline is not None:
        segment_timings = timeline.get("segmentTimings") or []
        timeline["cacheHitCount"] = sum(
            1 for item in segment_timings if item.get("cacheHit") is True
        )
        timeline["generatedSegmentCount"] = sum(
            1
            for item in segment_timings
            if item.get("cacheHit") is False and item.get("audioSize")
        )
    if missing_audio_segments:
        logger.warning(
            "[voice.agent_speech] built_with_missing_audio request_id=%s missing=%s total=%s missing_indexes=%s",
            effective_request_id,
            len(missing_audio_segments),
            len(built_segments),
            [segment.index for segment in missing_audio_segments],
        )
        try:
            combined_fallback_segments = await _build_combined_fallback_segment()
            if combined_fallback_segments:
                logger.info(
                    "[voice.agent_speech] using_combined_fallback request_id=%s total=%s",
                    effective_request_id,
                    len(combined_fallback_segments),
                )
                mark_voice_timeline(timeline, "backendTtsBuildCompletedAt")
                _set_voice_timeline_value(
                    timeline,
                    "backendTtsBuildMs",
                    round((time.perf_counter() - build_started_at) * 1000),
                )
                log_voice_timeline("agent_speech", timeline)
                return combined_fallback_segments
        except Exception as exc:
            logger.warning(
                "[voice.agent_speech] combined_fallback_failed request_id=%s error=%s",
                effective_request_id,
                exc,
            )
    else:
        logger.info(
            "[voice.agent_speech] built_all_audio request_id=%s total=%s",
            effective_request_id,
            len(built_segments),
        )
    mark_voice_timeline(timeline, "backendTtsBuildCompletedAt")
    _set_voice_timeline_value(
        timeline,
        "backendTtsBuildMs",
        round((time.perf_counter() - build_started_at) * 1000),
    )
    log_voice_timeline("agent_speech", timeline)
    return list(built_segments)


async def cleanup_tts_storage() -> None:
    """오래된 동적 TTS 파일과 만료된 캐시 파일을 정리한다."""
    roots = list(dict.fromkeys([_STATIC_TTS_ROOT, _LEGACY_STATIC_TTS_ROOT]))
    await asyncio.gather(
        *[asyncio.to_thread(_cleanup_tts_root, root) for root in roots]
    )


def _cleanup_tts_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    removed_dynamic = 0
    removed_cache = 0

    for child in root.iterdir():
        try:
            if child.name == _TTS_CACHE_DIRNAME:
                removed_cache += _cleanup_cache_dir(child, now)
                continue

            if child.is_dir():
                age_seconds = now - child.stat().st_mtime
                if age_seconds >= _DYNAMIC_TTS_TTL_SECONDS:
                    shutil.rmtree(child, ignore_errors=True)
                    removed_dynamic += 1
                continue

            age_seconds = now - child.stat().st_mtime
            if age_seconds >= _DYNAMIC_TTS_TTL_SECONDS:
                child.unlink(missing_ok=True)
                removed_dynamic += 1
        except Exception as exc:
            logger.warning("[voice.tts.cleanup] failed path=%s error=%s", child, exc)

    if removed_dynamic or removed_cache:
        logger.info(
            "[voice.tts.cleanup] root=%s removed_dynamic=%s removed_cache=%s",
            root,
            removed_dynamic,
            removed_cache,
        )


def _cleanup_cache_dir(cache_dir: Path, now: float) -> int:
    cache_dir.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in cache_dir.iterdir():
        try:
            age_seconds = now - child.stat().st_mtime
            if age_seconds < _CACHED_TTS_TTL_SECONDS:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            removed += 1
        except Exception as exc:
            logger.warning(
                "[voice.tts.cleanup] cache_failed path=%s error=%s",
                child,
                exc,
            )
    return removed


def _tts_cache_key(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    digest = hashlib.sha256(
        f"{_TTS_MODEL}|{','.join(_TTS_FALLBACK_MODELS)}|{_TTS_VOICE}|{normalized}".encode(
            "utf-8"
        )
    ).hexdigest()
    return digest


def _split_long_tts_segment(text: str, *, max_length: int = 64) -> list[str]:
    compact = text.strip()
    if len(compact) <= max_length:
        return [compact]

    segments: list[str] = []
    remaining = compact
    split_pattern = re.compile(r"[,，·:：]\s*|\s+")
    while len(remaining) > max_length:
      window = remaining[:max_length + 8]
      split_at = -1
      for match in split_pattern.finditer(window):
          split_at = match.end()
      if split_at <= 0:
          split_at = max_length
      head = remaining[:split_at].strip()
      if head:
          segments.append(head)
      remaining = remaining[split_at:].strip()
      if not remaining:
          break
    if remaining:
        segments.append(remaining)
    return segments


def _tts_prompt(text: str) -> str:
    return (
        "Read the exact following Korean text in Korean. "
        "Speak like a warm, affectionate daughter helping an older parent shop. "
        "Use a bright, reassuring, and very kind tone. "
        "Keep the voice gentle, patient, and easy for older adults to understand. "
        "Speak about 1.2x faster than a neutral default pace without sounding rushed. "
        "Pause naturally between sentences. "
        "Pronounce prices, quantities, dates, addresses, and payment-related words very clearly. "
        "Sound friendly and comforting, never cold or robotic. "
        "Do not add, remove, or change any words.\n"
        f"{text}"
    )


def _extract_audio_payload(response: types.GenerateContentResponse) -> bytes:
    """Gemini TTS 응답에서 inline audio payload를 꺼낸다."""
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if not inline_data:
                continue
            data = getattr(inline_data, "data", None)
            if isinstance(data, bytes):
                return data
            if isinstance(data, str) and data:
                return base64.b64decode(data)
    return b""


def _extract_audio_mime_type(response: types.GenerateContentResponse) -> str | None:
    """Gemini TTS 응답의 inline audio MIME type을 로그용으로 꺼낸다."""
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data:
                return getattr(inline_data, "mime_type", None)
    return None


def _provider_error_detail(exc: Exception) -> dict:
    """Gemini SDK 예외에서 provider 정보를 최대한 구조화한다."""
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)

    error = getattr(exc, "error", None)
    if isinstance(error, dict):
        status = status or error.get("status")
        code = code or error.get("code")
        message = error.get("message") or message

    return {
        "provider_status": str(status) if status is not None else None,
        "provider_error_code": str(code) if code is not None else None,
        "provider_message": str(message),
    }


def _wrap_pcm16_as_wav(
    pcm_bytes: bytes,
    *,
    sample_rate: int = _TTS_SAMPLE_RATE,
    channels: int = 1,
) -> bytes:
    """Gemini TTS의 PCM16 payload를 Flutter가 재생하기 쉬운 WAV로 감싼다."""
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm_bytes)
    riff_size = 36 + data_size

    header = b"".join(
        [
            b"RIFF",
            struct.pack("<I", riff_size),
            b"WAVE",
            b"fmt ",
            struct.pack("<I", 16),
            struct.pack("<H", 1),
            struct.pack("<H", channels),
            struct.pack("<I", sample_rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", 16),
            b"data",
            struct.pack("<I", data_size),
        ]
    )
    return header + pcm_bytes


def _concatenate_wav_segments(wav_segments: list[bytes]) -> bytes:
    if not wav_segments:
        return _wrap_pcm16_as_wav(b"")

    pcm_chunks = [_extract_pcm16_from_wav(wav_bytes) for wav_bytes in wav_segments]
    return _wrap_pcm16_as_wav(b"".join(pcm_chunks))


def _extract_pcm16_from_wav(wav_bytes: bytes) -> bytes:
    if len(wav_bytes) < 12 or wav_bytes[0:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return b""

    offset = 12
    total_length = len(wav_bytes)
    while offset + 8 <= total_length:
        chunk_id = wav_bytes[offset:offset + 4]
        chunk_size = struct.unpack("<I", wav_bytes[offset + 4:offset + 8])[0]
        data_start = offset + 8
        data_end = data_start + chunk_size
        if data_end > total_length:
            return b""
        if chunk_id == b"data":
            return wav_bytes[data_start:data_end]
        offset = data_end + (chunk_size % 2)

    return b""


def _estimate_wav_duration_ms(wav_bytes: bytes) -> int:
    pcm_bytes = max(0, len(_extract_pcm16_from_wav(wav_bytes)))
    bytes_per_second = _TTS_SAMPLE_RATE * 2
    if bytes_per_second <= 0:
        return 1000
    duration_ms = round((pcm_bytes / bytes_per_second) * 1000)
    return max(700, duration_ms)

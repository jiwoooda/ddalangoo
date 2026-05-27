"""Gemini 기반 한국어 STT 서비스.

업로드된 오디오 파일을 Gemini API로 전사해 텍스트를 반환한다.
API Key는 환경변수 GEMINI_API_KEY에서만 읽는다.

SDK: google-genai (google.generativeai는 deprecated)
"""

import os
import re

from google import genai
from google.genai import types
from fastapi import HTTPException

# ── 모델 / 프롬프트 ─────────────────────────────────────────────────────────

# gemini-2.5-flash (stable). Railway 환경변수 GEMINI_STT_MODEL로 재정의 가능.
# 구 모델명 gemini-2.5-flash-preview-05-20은 2026-05 기준 404 → gemini-2.5-flash로 통합됨.
_STT_MODEL = os.getenv("GEMINI_STT_MODEL", "models/gemini-2.5-flash")

# 기존 프론트 gemini_voice_service.dart STT 프롬프트 기준 + 쇼핑 도메인 표현 정확도 추가.
_STT_PROMPT = (
    "너는 한국어 음성 인식 엔진이다. "
    "오디오에서 실제로 들리는 사용자의 말만 한 줄 한국어 텍스트로 전사해라. "
    "오디오에 없는 문장, 대화 예시, 답변, 설명은 절대 만들지 마라. "
    "상품명, 수량, 가격, 배송지, 장바구니, 결제, 재주문과 관련된 표현은 특히 정확히 전사해라. "
    "말이 불명확하거나 배경음/무음이면 빈 문자열만 출력해라. "
    "줄바꿈 없이 텍스트만 출력해라."
)

_MAX_TRANSCRIPT_LENGTH = 200
_MIN_AUDIO_BYTES = 1000  # 너무 작은 파일은 무음으로 간주
_MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MB


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": "STT_CONFIG_ERROR",
                    "message": "STT 서비스가 설정되지 않았습니다.",
                }
            },
        )
    return genai.Client(api_key=api_key)


async def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """오디오 바이트를 Gemini로 전사해 텍스트를 반환한다.

    빈 발화이면 빈 문자열("")을 반환한다.
    오류 시 HTTPException을 발생시킨다.
    """
    if len(audio_bytes) < _MIN_AUDIO_BYTES:
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

    # 지원 MIME 타입 정규화
    safe_mime = _normalize_mime(mime_type)

    try:
        client = _get_client()
        response = await client.aio.models.generate_content(
            model=_STT_MODEL,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type=safe_mime),
                _STT_PROMPT,
            ],
        )
        raw = (response.text or "").strip()
        return _normalize_transcript(raw)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "STT_API_ERROR",
                    "message": f"음성 인식 중 오류가 발생했습니다: {exc}",
                }
            },
        ) from exc


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _normalize_mime(mime_type: str) -> str:
    """업로드 파일의 Content-Type을 Gemini가 허용하는 값으로 정규화한다."""
    mime = (mime_type or "").lower().split(";")[0].strip()
    _supported = {
        "audio/wav", "audio/wave", "audio/x-wav",
        "audio/mp4", "audio/mpeg", "audio/mp3",
        "audio/webm", "audio/ogg", "audio/flac",
        "audio/aac", "audio/x-m4a",
    }
    if mime in _supported:
        return mime
    # 확장자로 매핑 가능한 경우
    if "wav" in mime:
        return "audio/wav"
    if "mp3" in mime or "mpeg" in mime:
        return "audio/mpeg"
    if "webm" in mime:
        return "audio/webm"
    if "ogg" in mime:
        return "audio/ogg"
    if "flac" in mime:
        return "audio/flac"
    if "aac" in mime or "m4a" in mime or "mp4" in mime:
        return "audio/mp4"
    # 기본값
    return "audio/wav"


def _normalize_transcript(raw: str) -> str:
    """Gemini가 반환한 텍스트를 정제한다.

    - 여러 줄이면 첫 줄만 사용 (모델이 대화 예시를 만든 경우)
    - 앞뒤 인용부호 제거
    - 너무 긴 텍스트는 빈 문자열로 처리
    """
    if not raw:
        return ""

    lines = [l.strip() for l in re.split(r"[\r\n]+", raw) if l.strip()]
    if not lines:
        return ""

    # 여러 줄 → 모델이 할루시네이션했을 가능성이 높음
    if len(lines) > 1:
        return ""

    text = lines[0]

    # 앞뒤 인용부호 제거
    quotes = ('"', "'", "“", "”", "‘", "’")
    while text and text[0] in quotes:
        text = text[1:].lstrip()
    while text and text[-1] in quotes:
        text = text[:-1].rstrip()

    if len(text) > _MAX_TRANSCRIPT_LENGTH:
        return ""

    return text

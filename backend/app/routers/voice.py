"""POST /api/voice/stt — OpenAI 기반 한국어 음성 전사 엔드포인트."""

import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.schemas.voice import (
    SttResponse,
    TtsRequest,
    TtsResponse,
    TurnDetectionRequest,
    TurnDetectionResponse,
)
from app.services import voice_service

router = APIRouter(prefix="/voice", tags=["Voice"])
logger = logging.getLogger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_VAD_TEST_DIR = _BACKEND_DIR / "VAD_test"


def _resolve_uploaded_stt_mime_type(filename: str, content_type: str | None) -> str:
    normalized = (content_type or "").lower().split(";")[0].strip()
    if normalized and normalized != "application/octet-stream":
        return normalized

    extension = Path(filename).suffix.lower()
    mime_by_extension = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    return mime_by_extension.get(extension, "audio/wav")


def _save_uploaded_stt_file(filename: str, audio_bytes: bytes) -> Path:
    _VAD_TEST_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename).strip("._")
    if not safe_name:
        safe_name = "stt_upload.wav"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output_path = _VAD_TEST_DIR / f"{timestamp}_{safe_name}"
    output_path.write_bytes(audio_bytes)
    return output_path


@router.post("/stt", response_model=SttResponse)
async def speech_to_text(file: UploadFile = File(...)) -> SttResponse:
    """업로드된 오디오 파일을 텍스트로 전사한다.

    - Content-Type: multipart/form-data
    - 필드명: file
    - 지원 포맷: WAV, MP3, MP4, WebM, OGG, FLAC, AAC, M4A
    - 응답: {"transcript": "전사된 텍스트"} (빈 발화면 빈 문자열)
    """
    logger.info("[voice.stt] request received")

    if file.filename is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_FILE",
                    "message": "오디오 파일이 첨부되지 않았습니다.",
                }
            },
        )

    audio_bytes = await file.read()
    mime_type = _resolve_uploaded_stt_mime_type(file.filename, file.content_type)
    logger.info(
        "[voice.stt] file received filename=%s content_type=%s size=%s",
        file.filename,
        mime_type,
        len(audio_bytes),
    )
    saved_path = _save_uploaded_stt_file(file.filename, audio_bytes)
    logger.info("[voice.stt] file saved path=%s", saved_path)

    transcript = await voice_service.transcribe_audio(audio_bytes, mime_type)
    logger.info("[voice.stt] transcript succeeded length=%s", len(transcript))
    return SttResponse(transcript=transcript)


@router.post("/turn-detection", response_model=TurnDetectionResponse)
async def detect_voice_turn(req: TurnDetectionRequest) -> TurnDetectionResponse:
    """STT transcript가 사용자 턴으로 완성됐는지 판단한다."""
    return await voice_service.detect_turn_completion(req)


@router.post("/tts", response_model=TtsResponse)
async def text_to_speech(req: TtsRequest) -> TtsResponse:
    """텍스트를 Gemini TTS 음성으로 변환한다.

    프론트에는 OpenAI/Gemini API key를 두지 않고, Railway 백엔드 환경변수만 사용한다.
    """
    text = req.text.strip()
    logger.info("[voice.tts] request received text_length=%s", len(text))
    if not text:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "INVALID_TEXT",
                    "message": "TTS로 읽을 텍스트가 비어 있습니다.",
                }
            },
        )

    audio_bytes, segments, total_duration_ms = await voice_service.synthesize_speech_bundle(text)
    logger.info("[voice.tts] response ready audio_size=%s", len(audio_bytes))
    return TtsResponse(
        audioBase64=voice_service.encode_audio_base64(audio_bytes),
        mimeType="audio/wav",
        segments=segments,
        totalDurationMs=total_duration_ms,
    )

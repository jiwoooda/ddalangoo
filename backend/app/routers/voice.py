"""POST /api/voice/stt — OpenAI 기반 한국어 음성 전사 엔드포인트."""

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.schemas.voice import SttResponse, TtsRequest, TtsResponse
from app.services import voice_service

router = APIRouter(prefix="/voice", tags=["Voice"])
logger = logging.getLogger(__name__)


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
    mime_type = file.content_type or "audio/wav"
    logger.info(
        "[voice.stt] file received filename=%s content_type=%s size=%s",
        file.filename,
        mime_type,
        len(audio_bytes),
    )

    transcript = await voice_service.transcribe_audio(audio_bytes, mime_type)
    logger.info("[voice.stt] transcript succeeded length=%s", len(transcript))
    return SttResponse(transcript=transcript)


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

import os
import tempfile
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SAMPLE_RATE = 16000
CHANNELS = 1


def transcribe_file(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=f,
            language="ko",
            response_format="json",
            prompt=(
                "한국어 쇼핑 보조 서비스 딸랑구의 사용자 음성입니다. "
                "상품명, 수량, 가격, 배송, 장바구니, 결제 관련 표현을 정확히 전사해주세요."
            ),
        )

    return result.text.strip()


def record_audio(seconds: int = 3) -> str:
    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
    )
    sd.wait()

    temp_file = tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    )
    temp_path = temp_file.name
    temp_file.close()

    sf.write(temp_path, audio, SAMPLE_RATE)

    return temp_path


def synthesize_speech(
    text: str,
    output_path: str = "assistant_response.mp3",
) -> str:
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="coral",
        input=text,
        instructions=(
            "한국어로 말해줘. "
            "고령층 사용자가 듣기 쉽도록 천천히, 또렷하게 말해줘. "
            "친근한 딸 같은 말투로 말해줘. "
            "문장은 짧게 끊어서 말해줘. "
            "가격, 수량, 날짜는 특히 또박또박 말해줘."
        ),
    )

    output_file = Path(output_path)
    response.write_to_file(output_file)

    return str(output_file)


def cleanup_file(path: str):
    Path(path).unlink(missing_ok=True)
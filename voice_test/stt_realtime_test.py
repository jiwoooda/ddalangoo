import os
import time
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
CHUNK_SECONDS = 3


def record_chunk(seconds: int = CHUNK_SECONDS) -> np.ndarray:
    print(f"\n{seconds}초 동안 말씀해주세요...")
    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
    )
    sd.wait()
    return audio


def save_temp_wav(audio: np.ndarray) -> str:
    temp_file = tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    )
    temp_path = temp_file.name
    temp_file.close()

    sf.write(temp_path, audio, SAMPLE_RATE)
    return temp_path


def transcribe_wav(audio_path: str) -> str:
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


def realtime_like_stt_loop():
    print("딸랑구 STT 테스트를 시작합니다.")
    print("종료하려면 Ctrl+C를 누르세요.")

    try:
        while True:
            audio = record_chunk(CHUNK_SECONDS)
            temp_path = save_temp_wav(audio)

            start = time.time()
            transcript = transcribe_wav(temp_path)
            elapsed = time.time() - start

            Path(temp_path).unlink(missing_ok=True)

            if transcript:
                print("\n=== 전사 결과 ===")
                print(transcript)
                print(f"latency: {elapsed:.2f}s")
            else:
                print("전사 결과가 비어 있습니다.")

    except KeyboardInterrupt:
        print("\nSTT 테스트를 종료합니다.")


if __name__ == "__main__":
    realtime_like_stt_loop()
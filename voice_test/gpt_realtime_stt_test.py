import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def transcribe_file(audio_path: str) -> str:
    audio_file = Path(audio_path)

    if not audio_file.exists():
        raise FileNotFoundError(f"오디오 파일을 찾을 수 없습니다: {audio_file}")

    start = time.time()

    with audio_file.open("rb") as f:
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

    elapsed = time.time() - start

    print("\n=== STT 결과 ===")
    print(result.text)
    print(f"\nSTT latency: {elapsed:.2f}s")

    return result.text


if __name__ == "__main__":
    transcribe_file("sample.wav")
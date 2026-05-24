import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def text_to_speech(
    text: str,
    output_path: str = "ddalangoo_tts_test.mp3",
) -> str:
    start = time.time()

    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="coral",
        input=text,
        instructions=(
            "한국어로 말해줘. "
            "고령층 사용자가 듣기 쉽도록 천천히, 또렷하게 말해줘. "
            "친근한 딸 같은 말투로 말해줘. "
            "문장은 짧게 끊어서 말하고, 가격과 수량은 특히 또박또박 말해줘."
        ),
    )

    output_file = Path(output_path)
    response.write_to_file(output_file)

    elapsed = time.time() - start

    print(f"\nTTS 파일 생성 완료: {output_file.resolve()}")
    print(f"TTS latency: {elapsed:.2f}s")

    return str(output_file)


if __name__ == "__main__":
    sample_text = (
        "두부를 찾아봤어요. "
        "가장 저렴한 상품은 1,980원이에요. "
        "장바구니에 담을까요?"
    )

    text_to_speech(sample_text)
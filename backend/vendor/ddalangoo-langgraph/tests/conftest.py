"""pytest 전역 픽스처.

WON-33 — commerce_voice.render_voice 가 payment/node.py 에 배선되면(Unit 2+),
payment 테스트가 매 실행마다 LLM 을 호출하게 된다. 테스트를 결정론적으로
유지하기 위해 기본적으로 LLM 경로를 끄고, commerce_voice 의 결정론적 폴백
문구만 나오게 강제한다(폴백 문구 ≈ 배선 전 하드코딩 문구라 기존 assert 대부분
그대로 유지된다).

배선 전(Unit 1) 시점에는 어떤 테스트도 render_voice 를 호출하지 않으므로
이 픽스처는 완전한 no-op 이다 — 즉 이 픽스처 도입만으로 기존 테스트 결과가
바뀌면 안 된다.

실 LLM 을 타야 하는 테스트(commerce_voice 의 @pytest.mark.llm_smoke 등)는
자기 테스트에서 monkeypatch.undo() 로 이 픽스처를 해제한다.
"""
import pytest


@pytest.fixture(autouse=True)
def _force_commerce_voice_fallback(monkeypatch):
    try:
        from src.utils import commerce_voice
    except Exception:
        return
    monkeypatch.setattr(
        commerce_voice, "_try_llm", lambda bundle, timeout: None, raising=False,
    )

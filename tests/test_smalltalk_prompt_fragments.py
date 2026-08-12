import langgraph.errors

# 일부 개발 환경의 구버전 langgraph에는 애플리케이션이 사용하는 NodeError가
# 없다. 이 테스트는 에러 핸들러를 실행하지 않으므로 수집 시 타입 자리만 둔다.
if not hasattr(langgraph.errors, "NodeError"):
    class NodeError(Exception):
        pass

    langgraph.errors.NodeError = NodeError

from src.agents.smalltalk_agent import (
    _next_name_greeting_pending,
    check_episode_verbatim_copy,
    is_thin_reply,
    select_style_pattern,
)
from src.prompts.smalltalk_prompt import SMALLTALK_EPISODE_BANK


def test_episode_verbatim_copy_detects_observed_regression():
    reply = "저는 요리를 잘 못해서 가끔 라면 끓이다가 딴짓하는 사이에 다 태워먹곤 해요."
    assert check_episode_verbatim_copy(reply, SMALLTALK_EPISODE_BANK["burnt_ramen"])


def test_episode_verbatim_copy_allows_rewritten_detail():
    reply = "저도 냄비 올려둔 걸 깜빡해서 저녁을 배달로 바꾼 날이 있었어요."
    assert not check_episode_verbatim_copy(reply, SMALLTALK_EPISODE_BANK["burnt_ramen"])


def test_thin_reply_and_style_bias():
    assert is_thin_reply("네 맞아요", {})
    assert not is_thin_reply("네 맞아요", {"household_size": 1})
    key, _ = select_style_pattern([], is_thin_reply=True)
    assert key in {"guess", "balance"}


def test_thin_reply_style_bias_respects_recent_patterns():
    key, _ = select_style_pattern(["guess"], is_thin_reply=True)
    assert key == "balance"


def test_chat_prompt_exposes_pivot_fragment_slot():
    from src.prompts.smalltalk_prompt import SMALLTALK_CHAT_PROMPT

    assert "{topic_pivot_hint}" in SMALLTALK_CHAT_PROMPT


def test_name_greeting_is_consumed_even_when_llm_repeats_name():
    assert not _next_name_greeting_pending(
        was_pending=True,
        greeting_consumed=True,
        extracted_name="김철수",
        previous_name="김철수",
    )


def test_name_greeting_waits_when_higher_priority_fragment_prevents_use():
    assert _next_name_greeting_pending(
        was_pending=True,
        greeting_consumed=False,
        extracted_name="김철수",
        previous_name="김철수",
    )


def test_repeated_stored_name_does_not_rearm_greeting():
    assert not _next_name_greeting_pending(
        was_pending=False,
        greeting_consumed=False,
        extracted_name="김철수",
        previous_name="김철수",
    )


def test_new_name_arms_greeting_once():
    assert _next_name_greeting_pending(
        was_pending=False,
        greeting_consumed=False,
        extracted_name="김철수",
        previous_name=None,
    )


def test_repl_degraded_result_is_detectable():
    from src.agents.smalltalk_agent import _degraded_smalltalk_result
    from src.utils.retry import FailureClass

    result = _degraded_smalltalk_result(
        FailureClass.PERMANENT_TECHNICAL,
        RuntimeError("test"),
        is_first_greeting=True,
        onboarding_started_at="now",
    )
    assert result["degraded_mode"] is True
    assert result["immediate_response"] == "안녕하세요! 오늘은 뭘 도와드릴까요?"

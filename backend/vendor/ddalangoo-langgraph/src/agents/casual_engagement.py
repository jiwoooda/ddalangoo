"""
Casual Engagement — "잡담을 원하거나 아직 할 말이 없을 때 뭘 할지" 공용 로직.

두 군데가 공유한다:
  - fallback_orchestrator.py의 chat 분기 (대화 중 막혔을 때)
  - entry_engagement_node (세션 시작 시, route_session_start가 온보딩 완료
    유저를 여기로 보낸다)

우선순위는 동일하다: 만족도 체크인(안 물어본 구매이력) → 프로필 이어 묻기
(온보딩 때 못 채운 필드). 트리거(언제 불릴지)와 무관한 순수 "뭘 물을지"
로직이라 별도 모듈로 뽑았다 — 로직이 두 벌로 나뉘어 나중에 하나만 고쳐지는
걸 방지한다.

entry_engagement_node만 3번째 폴백(쇼핑 초대)이 있다 — 세션의 첫 대화인데
아무 말도 안 하면 어색하기 때문(fallback_orchestrator의 chat은 이미 진행
중인 대화라 성격이 다름, 그쪽은 자기 진단 LLM의 chat_reply로 대체한다).
"""
from typing import Any, Optional

from src.state.schema import ShoppingState
from src.tools import db_client
from src.agents.satisfaction_checkin import pick_satisfaction_candidate, start_satisfaction_checkin
from src.agents.profile_topup import pick_missing_profile_field, start_profile_topup


def pick_and_start_engagement(user_id: str) -> Optional[dict[str, Any]]:
    """만족도 체크인 우선, 없으면 프로필 이어 묻기. 물어볼 게 없으면 None."""
    if not user_id:
        return None
    candidate = pick_satisfaction_candidate(user_id)
    if candidate:
        pending_action = start_satisfaction_checkin(candidate)
        if pending_action:
            return pending_action
    missing_field = pick_missing_profile_field(user_id)
    if missing_field:
        return start_profile_topup(user_id, missing_field)
    return None


def entry_engagement_node(state: ShoppingState) -> dict:
    """세션 시작 시 온보딩 완료 유저에게 먼저 말을 건다(route_session_start
    참고) — 신규 유저가 smalltalk_agent로 먼저 인사받는 것과 대칭.

    가벼운 노드라 session_start_node/wait_for_input_node처럼 ShoppingState
    전체 타입을 그대로 쓴다(user_id 하나만 읽으므로 좁은 TypedDict는 과함)."""
    user_id = state.get("user_id", "")
    pending_action = pick_and_start_engagement(user_id)
    if not pending_action:
        # 물어볼 만족도/프로필이 하나도 없어도 조용히 넘어가지 않는다 - 세션의
        # 첫 대화인데 아무 말도 안 하면 어색하다(사용자 확인). ask_what_to_buy_node
        # 가 이미 쓰는 pending_action.type을 그대로 재사용 - 의미상 정확히 같은
        # 상황("지금 뭘 사고 싶은지 물어보는 중")이라 새 타입을 안 만든다.
        profile = db_client.get_profile(user_id) or {}
        name = profile.get("preferred_name")
        greeting = (
            f"{name}님, 안녕하세요! 오늘은 뭘 사고 싶으세요?"
            if name else "안녕하세요! 오늘은 뭘 사고 싶으세요?"
        )
        pending_action = {"type": "what_to_buy", "message": greeting}
    return {"pending_action": pending_action, "last_agent": "entry_engagement"}

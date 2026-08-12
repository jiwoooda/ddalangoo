"""Accessibility 자동화 실패 복구용 VLM planner.

이 서비스는 Android runtime이 보내온 screenshot + UI tree summary를 보고
허용된 작은 action JSON만 반환한다. 실제 클릭 실행은 Android가 담당한다.
"""

import base64
import json
import logging
import os

from fastapi import HTTPException
from google import genai
from google.genai import types

from app.schemas.agent import AutomationVlmPlanRequest, AutomationVlmPlanResponse

logger = logging.getLogger(__name__)

_VLM_PLANNER_MODEL = os.getenv("VLM_PLANNER_MODEL", "gemini-3.1-flash-lite-preview")
_MAX_SCREENSHOT_BYTES = 3 * 1024 * 1024

_VLM_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["tap", "tap_coordinate", "tap_node", "back", "swipe", "wait", "abort", "none"],
        },
        "targetDescription": {"type": "string"},
        "nodeId": {"type": "integer"},
        "x": {"type": "number", "minimum": 0, "maximum": 1},
        "y": {"type": "number", "minimum": 0, "maximum": 1},
        "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
        "distance": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["action", "confidence", "reason"],
    "additionalProperties": False,
}


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "")
    logger.info("[automation.vlm] GEMINI_API_KEY exists: %s", bool(api_key))
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": "VLM_CONFIG_ERROR",
                    "message": "VLM planner가 설정되지 않았습니다.",
                }
            },
        )
    return genai.Client(api_key=api_key)


def _decode_screenshot(screenshot: str) -> bytes:
    normalized = screenshot.strip()
    if "," in normalized and normalized.startswith("data:"):
        normalized = normalized.split(",", 1)[1]

    try:
        payload = base64.b64decode(normalized, validate=True)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_SCREENSHOT",
                    "message": "screenshot base64를 읽을 수 없습니다.",
                }
            },
        ) from exc

    if not payload:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "EMPTY_SCREENSHOT",
                    "message": "screenshot payload가 비어 있습니다.",
                }
            },
        )
    if len(payload) > _MAX_SCREENSHOT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": {
                    "code": "SCREENSHOT_TOO_LARGE",
                    "message": "screenshot payload가 너무 큽니다.",
                }
            },
        )
    return payload


def _is_rule_failure_recovery(req: AutomationVlmPlanRequest) -> bool:
    return req.fallbackReasonCode == "visual_sentinel_rule_target_missing"


def _recovery_mode(req: AutomationVlmPlanRequest) -> str:
    if req.fallbackReasonCode == "visual_sentinel_step_entry":
        return "STEP_ENTRY_SENTINEL"
    if _is_rule_failure_recovery(req):
        return "RULE_FAILURE_RECOVERY"
    if req.fallbackReasonCode.endswith("root_unavailable") or "system" in req.fallbackReasonCode:
        return "SYSTEM_RECOVERY"
    return "VISUAL_RECOVERY"


def _step_goal(req: AutomationVlmPlanRequest) -> str:
    if req.recoveryGoal:
        return (
            f"Move only toward canonical recoveryGoal={req.recoveryGoal}. "
            "Do not complete currentStep directly; Android rules will re-observe and advance."
        )

    goals = {
        "open_my_kurly": "Move to the My Kurly tab/page so the rule runtime can verify it.",
        "open_my_coupang": "Move to the My Coupang tab/page so the rule runtime can verify it.",
        "open_order_history": "Expose the order history entry or order history screen.",
        "open_search": "Expose the search entry or search input.",
        "search_input": "Expose an editable search input.",
        "search_submit": "Expose a submitted search results screen for the expected keyword.",
        "ensure_recommended_sort": "Expose or keep the recommended sort search results screen.",
        "select_product": "Expose the target product card.",
        "click_detail_add_to_cart": "Expose the add-to-cart control on the product detail page.",
        "select_option": "Expose or select the requested product option.",
        "confirm_option_add_to_cart": "Expose the option add-to-cart confirmation control.",
    }
    return goals.get(req.currentStep, "Recover just enough for the deterministic rule runtime to retry this same step.")


def _mode_instructions(req: AutomationVlmPlanRequest) -> str:
    recovery_mode = _recovery_mode(req)
    if req.recoveryGoal:
        return f"""
Mode: PURCHASE_HISTORY_CANONICAL_RECOVERY
- The deterministic purchase-history FSM is the authority for normal progression.
- Current screen classification: {req.currentScreen or "unknown"}
- Canonical recovery goal: {req.recoveryGoal}
- Perform at most one small action toward recoveryGoal, then Android will re-observe.
- Do not solve currentStep directly. Do not tap order history, product cards, cart buttons, search,
  or purchase-history list controls unless that control is strictly the nearest visible path to
  recoveryGoal.
- If currentScreen already matches recoveryGoal, return action="none".
- Prefer back when the current screen is a product/search/cart/detail page and the goal is a My page
  or order-history page.
""".strip()

    if recovery_mode == "STEP_ENTRY_SENTINEL":
        return """
Mode: STEP_ENTRY_SENTINEL
- Be strict. Return action="none" unless a visible blocker is actually present.
- You may close/dismiss popups, permission dialogs, loading blockers, or blocking overlays.
- Do not tap normal task progression controls such as My Kurly, My Coupang, order history,
  search, product cards, cart buttons, or option controls.
""".strip()
    if recovery_mode == "RULE_FAILURE_RECOVERY":
        return f"""
Mode: RULE_FAILURE_RECOVERY
- The deterministic rule runtime already failed to find the target for this same step.
- Step-local goal: {_step_goal(req)}
- You may perform exactly one small exploratory/recovery action that helps this same step become
  observable, including tapping a visible step target, tapping a safe coordinate, swiping a normal
  app surface, or pressing back from a wrong non-sensitive app screen.
- Allowed examples when they match currentStep:
  - currentStep=open_my_kurly: tap visible My Kurly / 마이컬리, or back out of a product/search/cart page.
  - currentStep=open_my_coupang: tap visible My Coupang / 마이쿠팡, or back out of a product/search/cart page.
  - currentStep=open_order_history: tap visible order history / 주문내역 / 주문목록.
- Do not decide success. Android will re-observe and the rule runtime will advance the step only
  after deterministic verification.
""".strip()
    if recovery_mode == "SYSTEM_RECOVERY":
        return """
Mode: SYSTEM_RECOVERY
- Only recover from Android/system permission or settings screens.
- Prefer back or safe denial/dismiss actions.
- Never tap sensitive permission grants, credentials, payment, or destructive controls.
""".strip()
    return """
Mode: VISUAL_RECOVERY
- Recover only clear blockers, unknown screens, or overlays.
- Prefer one conservative action, then let Android re-observe.
""".strip()


def _build_prompt(req: AutomationVlmPlanRequest) -> str:
    return f"""
You are a visual sentinel for an Android Accessibility automation runtime.

Goal:
- Your job is to perform at most one safe, step-local recovery action.
- Your action must never mark the step successful. Android will always re-observe and let the
  deterministic rule runtime verify whether the step can advance.
- The deterministic rule runtime owns all normal task progression, such as opening My Coupang,
  opening order history, searching, selecting a product, tapping cart buttons, or scrolling purchase history.
- Use both screenshot and UI tree summary. The UI tree may omit visual overlays, and visual
  elements may be visible even when no matching accessibility node exists.
- Return exactly one JSON action. Do not explain outside JSON.

{_mode_instructions(req)}

Decision rule:
- If the current screen looks like a normal app screen where the rule runtime can continue,
  return action="none".
- If recoveryGoal is present, do not finish currentStep directly. Choose at most one action that
  moves toward recoveryGoal, or return none if the screen already matches recoveryGoal.
- If there is a popup, modal, overlay, system permission dialog, loading blocker, or unknown
  blocking screen, return one safe recovery action.
- In RULE_FAILURE_RECOVERY only, if the rule runtime cannot see the step target but the target is
  visually clear and safe, you may tap it once. Otherwise do not navigate to the next normal task target.

Allowed actions:
- tap_node: tap an accessibility node id from the UI tree when it clearly matches the goal.
- tap_coordinate/tap: tap a safe normalized coordinate when the target is visible in the screenshot
  but no reliable node exists.
- back: press Android back only to dismiss a blocker, escape a modal, dismiss a system dialog,
  or recover from an explicit unexpected/wrong-screen retry.
- swipe: swipe only to recover from a blocker, such as a bottom sheet, drawer, carousel-style
  overlay, or explicit unexpected-screen retry. In RULE_FAILURE_RECOVERY, a single swipe is allowed
  when it may reveal the current step target.
- wait: wait if the screen is loading or uncertain.
- none: do nothing if the screen looks normal and no blocking popup/overlay is visible.
- abort: abort if the screen is sensitive, unsafe, or no safe action is visible.

Safety rules:
- Never tap payment, purchase, password, login credential, delete, or destructive controls.
- Prefer closing or dismissing visible popup overlays.
- If a popup contains both a do-not-show-again option such as "7일간 보지 않기",
  "오늘 하루 보지 않기", or "다시 보지 않기" and a close control such as "닫기",
  "X", or "×", prefer the close control. Treat do-not-show-again text as an
  optional choice, not the final dismiss action, and do not click it repeatedly.
- If an in-app popup asks to enable delivery/order notifications, do not opt in.
  Prefer a negative/dismissive control such as "싫어요", "아니요", "안 할래요",
  "받지 않기", "나중에", "닫기", "X", or "×". Never tap "알림 켜기",
  "알림 받기", "허용", or equivalent opt-in controls for delivery notifications.
- In STEP_ENTRY_SENTINEL, do not return actions for normal task progression. Forbidden examples:
  - tapping My Coupang / 마이쿠팡
  - tapping My Kurly / 마이컬리
  - tapping order history / 주문내역 / 주문목록
  - tapping search, search submit, product cards, cart buttons, option controls
  - swiping a normal list just to continue purchase-history collection
  - pressing back merely to navigate from a normal product/category page toward home
- Only tap/back/swipe when it is clearly a blocker recovery action, such as closing a popup,
  dismissing a permission dialog, escaping a blocking modal, or a RULE_FAILURE_RECOVERY action
  scoped to the currentStep goal.
- If fallbackReasonCode is visual_sentinel_step_entry, be extra strict:
  return none unless a visible blocker is actually present.
- If fallbackReasonCode is visual_sentinel_unexpected_screen or visual_sentinel_rule_target_missing,
  you may recover from a clearly wrong/blocking screen. For visual_sentinel_rule_target_missing,
  you may also tap/swipe/back toward the current step target only; never continue beyond it.
- Coordinates must be normalized x/y from 0.0 to 1.0.
- If action is tap or tap_coordinate, x and y are required.
- If action is tap_node, nodeId is required and must be one of the UI tree node ids.
- If action is swipe, direction is required. distance is optional; default to 0.55.
- If confidence is below 0.55, use wait or abort.
- VLM action success does not mean the current step succeeded; the Android rule runtime will retry the same step after your action.

Task:
- taskId: {req.taskId}
- platform: {req.platform}
- packageName: {req.packageName or ""}
- currentStep: {req.currentStep}
- currentScreen: {req.currentScreen or ""}
- recoveryGoal: {req.recoveryGoal or ""}
- fallbackReasonCode: {req.fallbackReasonCode}
- recoveryMode: {_recovery_mode(req)}
- stepGoal: {_step_goal(req)}
- expectedState: {req.expectedState or ""}
- observedState: {req.observedState or ""}

UI tree summary:
{req.uiTreeSummary}

Recent VLM actions:
{json.dumps(req.recentActions[-5:], ensure_ascii=False)}
""".strip()


def _looks_like_blocker_recovery(plan: AutomationVlmPlanResponse) -> bool:
    text = f"{plan.targetDescription or ''} {plan.reason or ''}".lower()
    blocker_keywords = [
        "popup",
        "pop-up",
        "overlay",
        "modal",
        "dialog",
        "permission",
        "notification",
        "dismiss",
        "close",
        "deny",
        "don't allow",
        "don’t allow",
        "not allow",
        "loading",
        "block",
        "blocking",
        "팝업",
        "오버레이",
        "모달",
        "권한",
        "알림",
        "닫기",
        "닫힘",
        "닫아",
        "종료",
        "허용 안함",
        "차단",
        "로딩",
    ]
    return any(keyword in text for keyword in blocker_keywords)


def _looks_like_normal_task_progression(plan: AutomationVlmPlanResponse) -> bool:
    text = f"{plan.targetDescription or ''} {plan.reason or ''}".lower()
    progression_keywords = [
        "my coupang",
        "마이쿠팡",
        "my kurly",
        "마이컬리",
        "order history",
        "order list",
        "주문내역",
        "주문 내역",
        "주문목록",
        "search",
        "검색",
        "product card",
        "상품 카드",
        "cart",
        "장바구니",
        "option",
        "옵션",
        "bottom navigation",
        "navigation bar",
        "home screen",
        "category page",
        "product detail page",
    ]
    return any(keyword in text for keyword in progression_keywords)


def _coerce_step_entry_sentinel_plan(
    req: AutomationVlmPlanRequest,
    plan: AutomationVlmPlanResponse,
) -> AutomationVlmPlanResponse:
    if req.fallbackReasonCode != "visual_sentinel_step_entry":
        return plan
    if plan.action in {"none", "wait", "abort"}:
        return plan
    if _looks_like_blocker_recovery(plan) and not _looks_like_normal_task_progression(plan):
        return plan

    logger.warning(
        "[automation.vlm] coerced step-entry task progression action to none taskId=%s step=%s action=%s reason=%s",
        req.taskId,
        req.currentStep,
        plan.action,
        plan.reason,
    )
    return AutomationVlmPlanResponse(
        action="none",
        confidence=min(plan.confidence, 0.8),
        reason=(
            "Step-entry visual sentinel observed no clear blocker. "
            "Normal task progression is reserved for the rule-based runtime."
        ),
    )


def _coerce_recovery_goal_plan(
    req: AutomationVlmPlanRequest,
    plan: AutomationVlmPlanResponse,
) -> AutomationVlmPlanResponse:
    if not req.recoveryGoal:
        return plan
    if plan.action in {"none", "wait", "abort", "back", "swipe"}:
        return plan

    plan_text = f"{plan.targetDescription or ''} {plan.reason or ''}".lower()
    goal = req.recoveryGoal.lower()
    current_screen = (req.currentScreen or "").lower()

    if current_screen == goal:
        return AutomationVlmPlanResponse(
            action="none",
            confidence=min(plan.confidence, 0.85),
            reason="Recovery goal is already visible; deterministic rules should re-observe.",
        )

    my_page_goals = {"my_kurly", "my_coupang"}
    order_history_keywords = ["order history", "order list", "주문내역", "주문 내역", "주문목록"]
    task_progression_keywords = [
        "product",
        "상품",
        "cart",
        "장바구니",
        "search",
        "검색",
        "option",
        "옵션",
    ]

    if goal in my_page_goals and any(keyword in plan_text for keyword in order_history_keywords):
        logger.warning(
            "[automation.vlm] coerced purchase-history recovery beyond my-page goal taskId=%s step=%s goal=%s action=%s",
            req.taskId,
            req.currentStep,
            req.recoveryGoal,
            plan.action,
        )
        return AutomationVlmPlanResponse(
            action="none",
            confidence=min(plan.confidence, 0.75),
            reason="VLM may not skip canonical My page recovery and directly open order history.",
        )

    if goal == "order_history" and any(keyword in plan_text for keyword in task_progression_keywords):
        logger.warning(
            "[automation.vlm] coerced purchase-history recovery task progression taskId=%s step=%s goal=%s action=%s",
            req.taskId,
            req.currentStep,
            req.recoveryGoal,
            plan.action,
        )
        return AutomationVlmPlanResponse(
            action="none",
            confidence=min(plan.confidence, 0.75),
            reason="VLM recovery must not interact with product/search/cart controls during purchase history recovery.",
        )

    return plan


def _response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        for part in parts or []:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                return part_text.strip()
    return ""


async def plan_vlm_recovery(req: AutomationVlmPlanRequest) -> AutomationVlmPlanResponse:
    screenshot_bytes = _decode_screenshot(req.screenshot)
    client = _get_client()
    logger.info(
        "[automation.vlm] request taskId=%s step=%s reason=%s model=%s",
        req.taskId,
        req.currentStep,
        req.fallbackReasonCode,
        _VLM_PLANNER_MODEL,
    )

    try:
        response = await client.aio.models.generate_content(
            model=_VLM_PLANNER_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=_build_prompt(req)),
                        types.Part.from_bytes(data=screenshot_bytes, mime_type="image/jpeg"),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=_VLM_ACTION_SCHEMA,
            ),
        )
        raw_text = _response_text(response)
        if not raw_text:
            raise ValueError("empty VLM response")
        payload = json.loads(raw_text)
        plan = AutomationVlmPlanResponse(**payload)
        if plan.action in {"tap", "tap_coordinate"} and (plan.x is None or plan.y is None):
            raise ValueError(f"{plan.action} action requires x and y")
        if plan.action == "tap_node" and plan.nodeId is None:
            raise ValueError("tap_node action requires nodeId")
        if plan.action == "swipe" and plan.direction is None:
            raise ValueError("swipe action requires direction")
        plan = _coerce_step_entry_sentinel_plan(req, plan)
        plan = _coerce_recovery_goal_plan(req, plan)
        logger.info(
            "[automation.vlm] response taskId=%s action=%s confidence=%s reason=%s",
            req.taskId,
            plan.action,
            plan.confidence,
            plan.reason,
        )
        return plan
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[automation.vlm] failed taskId=%s", req.taskId)
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "VLM_PLANNER_FAILED",
                    "message": f"VLM planner 호출에 실패했습니다: {exc}",
                }
            },
        ) from exc

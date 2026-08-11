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
        "action": {"type": "string", "enum": ["tap", "wait", "abort"]},
        "x": {"type": "number", "minimum": 0, "maximum": 1},
        "y": {"type": "number", "minimum": 0, "maximum": 1},
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


def _build_prompt(req: AutomationVlmPlanRequest) -> str:
    return f"""
You are a conservative mobile UI recovery planner for an Android Accessibility automation runtime.

Goal:
- The rule-based runtime is stuck because a popup may be blocking the intended step.
- Return exactly one safe action as JSON. Do not explain outside JSON.

Allowed actions:
- tap: tap a safe normalized coordinate to dismiss a blocking popup.
- wait: wait if the screen is loading or uncertain.
- abort: abort if the screen is sensitive, unsafe, or no safe action is visible.

Safety rules:
- Never tap payment, purchase, password, login credential, delete, or destructive controls.
- Prefer closing or dismissing visible popup overlays.
- Coordinates must be normalized x/y from 0.0 to 1.0.
- If action is tap, x and y are required.
- If confidence is below 0.55, use wait or abort.
- VLM action success does not mean the current step succeeded; the Android rule runtime will retry the same step after your action.

Task:
- taskId: {req.taskId}
- platform: {req.platform}
- packageName: {req.packageName or ""}
- currentStep: {req.currentStep}
- fallbackReasonCode: {req.fallbackReasonCode}
- expectedState: {req.expectedState or ""}
- observedState: {req.observedState or ""}

UI tree summary:
{req.uiTreeSummary}
""".strip()


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
        if plan.action == "tap" and (plan.x is None or plan.y is None):
            raise ValueError("tap action requires x and y")
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

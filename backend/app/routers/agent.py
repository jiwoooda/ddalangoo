from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.agent import ShoppingRequest, MessageRequest, ConfirmRequest, PromptRequest, AgentResponse
from app.schemas.payment import WebviewResultRequest
from app.services import (
    agent_progress_service,
    agent_service,
    payment_service,
    webview_progress_service,
)

router = APIRouter(prefix="/agent", tags=["Agent"])

@router.post("/shopping-requests", response_model=AgentResponse)
async def start_shopping(req: ShoppingRequest, db: AsyncSession = Depends(get_db)):
    return await agent_service.start_shopping(db, req)

@router.get("/conversations/{conversationId}", response_model=AgentResponse)
async def get_conversation(conversationId: int, db: AsyncSession = Depends(get_db)):
    return await agent_service.get_conversation(db, conversationId)

@router.post("/conversations/{conversationId}/messages", response_model=AgentResponse)
async def send_message(
    conversationId: int,
    req: MessageRequest,
    db: AsyncSession = Depends(get_db),
):
    return await agent_service.send_message(db, conversationId, req)

@router.post("/conversations/{conversationId}/confirm", response_model=AgentResponse)
async def confirm_action(
    conversationId: int,
    req: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    return await agent_service.confirm_action(db, conversationId, req)

@router.post("/prompts", response_model=AgentResponse)
async def prompt_response(req: PromptRequest):
    return await agent_service.generate_prompt_response(req)

@router.post("/conversations/{conversationId}/payments/webview-result")
async def webview_result(
    conversationId: int,
    req: WebviewResultRequest,
    db: AsyncSession = Depends(get_db),
):
    return await payment_service.handle_webview_result_db(db, conversationId, req)


@router.post("/conversations/{conversationId}/cancel")
async def cancel_conversation(conversationId: int):
    """
    실행 중인 Playwright 웹뷰 작업에 취소 신호를 보낸다.

    현재 request_cancel()은 프로세스 내부 threading.Event 기반이다.
    Railway 등에서 여러 worker/process로 뜨면 worker 간 Event가 공유되지 않으므로,
    운영 확장 시 Redis/pubsub 같은 외부 cancel store로 바꿔야 한다.
    """
    from src.tools.webview_tool import request_cancel

    request_cancel()
    return {"ok": True}


@router.websocket("/conversations/{conversationId}/webview")
async def webview_progress(conversationId: int, websocket: WebSocket):
    await webview_progress_service.connect(conversationId, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        webview_progress_service.disconnect(conversationId, websocket)


@router.websocket("/progress/{channelId}")
async def agent_progress(channelId: str, websocket: WebSocket):
    await agent_progress_service.connect(channelId, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        agent_progress_service.disconnect(channelId, websocket)


@router.get("/conversations/{conversationId}/webview/status")
def webview_status(conversationId: int):
    return webview_progress_service.get_status_or_default(conversationId)


@router.get("/conversations/{conversationId}/webview/screenshot")
def webview_screenshot(conversationId: int):
    screenshot = webview_progress_service.get_latest_screenshot(conversationId)
    if not screenshot:
        return Response(status_code=204)
    return Response(
        content=screenshot,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )

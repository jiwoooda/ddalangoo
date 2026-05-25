from fastapi import APIRouter, Response, WebSocket, WebSocketDisconnect
from app.schemas.agent import ShoppingRequest, MessageRequest, ConfirmRequest, AgentResponse
from app.schemas.payment import WebviewResultRequest
from app.services import agent_service, payment_service, webview_progress_service

router = APIRouter(prefix="/agent", tags=["Agent"])

@router.post("/shopping-requests", response_model=AgentResponse)
def start_shopping(req: ShoppingRequest):
    return agent_service.start_shopping(req)

@router.get("/conversations/{conversationId}", response_model=AgentResponse)
def get_conversation(conversationId: int):
    return agent_service.get_conversation(conversationId)

@router.post("/conversations/{conversationId}/messages", response_model=AgentResponse)
def send_message(conversationId: int, req: MessageRequest):
    return agent_service.send_message(conversationId, req)

@router.post("/conversations/{conversationId}/confirm", response_model=AgentResponse)
def confirm_action(conversationId: int, req: ConfirmRequest):
    return agent_service.confirm_action(conversationId, req)

@router.post("/conversations/{conversationId}/payments/webview-result")
def webview_result(conversationId: int, req: WebviewResultRequest):
    return payment_service.handle_webview_result(conversationId, req)


@router.websocket("/conversations/{conversationId}/webview")
async def webview_progress(conversationId: int, websocket: WebSocket):
    await webview_progress_service.connect(conversationId, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        webview_progress_service.disconnect(conversationId, websocket)


@router.get("/conversations/{conversationId}/webview/status")
def webview_status(conversationId: int):
    return webview_progress_service.get_latest_status(conversationId) or {
        "type": "webview_progress",
        "conversationId": conversationId,
        "status": "idle",
    }


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

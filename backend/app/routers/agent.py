from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
from app.schemas.agent import ShoppingRequest, MessageRequest, ConfirmRequest, AgentResponse
from app.schemas.payment import WebviewResultRequest
from app.services import agent_service, payment_service
from app.services.playwright_stream_service import playwright_stream_service

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


@router.websocket("/conversations/{conversationId}/playwright-stream")
async def playwright_stream(conversationId: int, websocket: WebSocket):
    await websocket.accept()
    last_version = -1

    try:
        while True:
            event = playwright_stream_service.latest(conversationId)
            if event is not None and event.get("version", -1) != last_version:
                await websocket.send_json(event)
                last_version = event["version"]
                if event.get("final"):
                    await asyncio.sleep(0.2)
                    break
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        return
    finally:
        await websocket.close()

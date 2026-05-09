from fastapi import APIRouter
from app.schemas.agent import ShoppingRequest, MessageRequest, ConfirmRequest, AgentResponse
from app.schemas.payment import WebviewResultRequest
from app.services import agent_service, payment_service

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

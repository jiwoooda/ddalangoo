from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.agent import ShoppingRequest, MessageRequest, ConfirmRequest, AgentResponse
from app.schemas.payment import WebviewResultRequest
from app.services import agent_service, payment_service

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

@router.post("/conversations/{conversationId}/payments/webview-result")
async def webview_result(
    conversationId: int,
    req: WebviewResultRequest,
    db: AsyncSession = Depends(get_db),
):
    return await payment_service.handle_webview_result_db(db, conversationId, req)

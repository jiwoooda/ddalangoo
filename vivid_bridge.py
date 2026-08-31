"""
VIVID(mphora.ai) 가상유저 검증 연동용 최소 HTTP 브릿지.

목적: VIVID의 target kind="http"로 붙일 수 있는 단일 /chat 엔드포인트를
제공한다. 프로덕션 백엔드(backend/app, main.py, 실 Postgres)를 거치지
않고 에이전트 그래프(build_graph)만 직접 호출한다 — DB_MODE는 기본값
"mock"을 그대로 쓰므로 실 DB 연결/마이그레이션 없이 완전히 독립
구동된다. 에이전트 시스템 자체는 이미 완성돼 있고 실 배포/DB 세팅만
아직이라, 이 얇은 래퍼만으로 외부 검증을 먼저 받을 수 있다.

안전 주의: USE_REAL_BROWSER를 여기서 절대 켜지 않는다 — VIVID가 자동으로
다수의 페르소나 대화를 병렬로 돌리므로, 실제 브라우저 결제 자동화가
켜져 있으면 진짜 주문이 발생할 위험이 있다. payment/node.py는 이 값을
아예 참조하지 않으므로(브라우저 자동화는 backend/app 쪽 별도 서비스)
기본 상태로는 안전하다.

세션 유지: MemorySaver(인메모리) 체크포인터를 프로세스 생존 기간 동안
공유한다 — 서버가 재시작되면 진행 중이던 대화는 끊긴다(테스트 브릿지
용도라 허용 가능한 제약).

실행:
    uvicorn vivid_bridge:app --host 0.0.0.0 --port 8787

인증(선택): 환경변수 VIVID_BRIDGE_TOKEN을 설정하면 모든 요청에
"Authorization: Bearer <token>" 헤더를 요구한다. 안 설정하면 인증 없이 오픈.
"""
import os
import time
import uuid
from typing import Literal, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.graph.builder import build_graph
from src.state.schema import get_default_shopping_state

app = FastAPI(title="Ddalangoo VIVID Bridge", version="0.1.0")

_graph = build_graph()
_known_sessions: set[str] = set()

_BRIDGE_TOKEN = os.getenv("VIVID_BRIDGE_TOKEN")


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    stage: str


class OpenAIChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class OpenAIChatCompletionRequest(BaseModel):
    model: str
    messages: list[OpenAIChatMessage]
    session_id: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False


class OpenAIResponseMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class OpenAIChoice(BaseModel):
    index: int = 0
    message: OpenAIResponseMessage
    finish_reason: Literal["stop"] = "stop"


class OpenAIChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: Literal["ddalangoo"] = "ddalangoo"
    choices: list[OpenAIChoice]
    session_id: str


class OpenAIModel(BaseModel):
    id: str
    object: Literal["model"] = "model"
    owned_by: str


class OpenAIModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[OpenAIModel]


def _check_auth(authorization: Optional[str]) -> None:
    if not _BRIDGE_TOKEN:
        return
    if authorization != f"Bearer {_BRIDGE_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _extract_reply(config: dict) -> tuple[str, str]:
    vals = _graph.get_state(config).values
    reply = ""
    for msg in reversed(vals.get("messages", [])):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            reply = msg["content"]
            break
        if getattr(msg, "type", None) == "ai":
            reply = msg.content
            break
    return reply, vals.get("stage", "idle")


def _initialize_session(session_id: str, user_id: Optional[str]) -> tuple[dict, str, str]:
    """필요할 때만 LangGraph thread를 만들고 선제 인사 결과를 돌려준다."""
    config = {"configurable": {"thread_id": session_id}}
    if session_id in _known_sessions:
        return config, "", "idle"

    initial_state = get_default_shopping_state(user_id or session_id, session_id)
    _graph.invoke(initial_state, config)
    _known_sessions.add(session_id)
    proactive_reply, proactive_stage = _extract_reply(config)
    return config, proactive_reply, proactive_stage


def _run_agent_turn(
    message: str,
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    first_turn_policy: Literal["return_greeting", "process_user"] = "return_greeting",
) -> ChatResponse:
    """한 user turn을 기존 LangGraph에 전달한다.

    ``return_greeting``은 기존 /chat의 신규 세션 동작을 보존한다. OpenAI
    adapter는 ``process_user``를 써서 초기 선제 인사가 있더라도 같은 HTTP
    요청 안에서 user message까지 반드시 처리한다.
    """
    resolved_session_id = session_id or f"vivid-{uuid.uuid4().hex[:12]}"
    config, proactive_reply, proactive_stage = _initialize_session(resolved_session_id, user_id)

    if proactive_reply and first_turn_policy == "return_greeting":
        return ChatResponse(
            session_id=resolved_session_id,
            reply=proactive_reply,
            stage=proactive_stage,
        )

    _graph.update_state(config, {"messages": [{"role": "user", "content": message}]})
    try:
        _graph.invoke(None, config)
    except Exception as exc:
        # 기존 /chat의 오류 계약을 유지한다. OpenAI endpoint는 이 예외의 내부
        # detail을 외부에 노출하지 않고 일반화된 error envelope로 바꾼다.
        raise HTTPException(
            status_code=500,
            detail=f"agent error: {type(exc).__name__}: {exc}",
        ) from exc

    reply, stage = _extract_reply(config)
    return ChatResponse(session_id=resolved_session_id, reply=reply, stage=stage)


def _openai_error(
    status_code: int,
    message: str,
    code: str,
    *,
    param: Optional[str] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": "invalid_request_error" if status_code < 500 else "server_error",
                "param": param,
                "code": code,
            }
        },
    )


def _last_user_message(messages: list[OpenAIChatMessage]) -> Optional[str]:
    # 이번 adapter는 stateless history reconstruction을 하지 않는다. session_id가
    # 없더라도 과거 system/assistant/user history는 재주입하지 않고 마지막 user
    # message 하나만 새 LangGraph session에 전달한다.
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, authorization: Optional[str] = Header(default=None)):
    """VIVID persona 한 턴 → 딸랑구 에이전트 응답 한 턴.

    session_id를 안 보내면 새 대화로 취급해 새로 발급한다. 이후 턴부터는
    같은 session_id를 실어 보내야 대화가 이어진다(VIVID 쪽이 응답의
    session_id를 다음 요청에 그대로 실어 보내는 걸 전제).
    """
    _check_auth(authorization)
    return _run_agent_turn(
        req.message,
        session_id=req.session_id,
        user_id=req.user_id,
        first_turn_policy="return_greeting",
    )


@app.post("/v1/chat/completions")
def openai_chat_completions(
    req: OpenAIChatCompletionRequest,
    authorization: Optional[str] = Header(default=None),
):
    try:
        _check_auth(authorization)
    except HTTPException:
        return _openai_error(401, "Invalid authentication credentials.", "invalid_api_key")

    if req.model != "ddalangoo":
        return _openai_error(
            404, f"The model {req.model!r} does not exist.", "model_not_found", param="model"
        )
    if req.stream:
        return _openai_error(
            400, "Streaming is not supported.", "unsupported_parameter", param="stream"
        )
    if not req.messages:
        return _openai_error(400, "messages must not be empty.", "invalid_messages", param="messages")

    user_message = _last_user_message(req.messages)
    if user_message is None or not user_message.strip():
        return _openai_error(
            400, "A non-empty user message is required.", "missing_user_message", param="messages"
        )

    try:
        result = _run_agent_turn(
            user_message,
            session_id=req.session_id,
            first_turn_policy="process_user",
        )
    except Exception:
        # LLM/provider 이름, 예외 타입, stack trace 등 내부 실행 정보를 숨긴다.
        return _openai_error(500, "The agent could not complete the request.", "agent_error")

    response = OpenAIChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        choices=[
            OpenAIChoice(message=OpenAIResponseMessage(content=result.reply)),
        ],
        session_id=result.session_id,
    )
    return response


@app.get("/v1/models")
def openai_models(authorization: Optional[str] = Header(default=None)):
    try:
        _check_auth(authorization)
    except HTTPException:
        return _openai_error(401, "Invalid authentication credentials.", "invalid_api_key")
    return OpenAIModelList(
        data=[OpenAIModel(id="ddalangoo", owned_by="ddalangoo")],
    )

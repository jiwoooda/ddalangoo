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
import uuid
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Header, HTTPException
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

    session_id = req.session_id or f"vivid-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": session_id}}

    if session_id not in _known_sessions:
        initial_state = get_default_shopping_state(req.user_id or session_id, session_id)
        _graph.invoke(initial_state, config)
        _known_sessions.add(session_id)

    _graph.update_state(config, {"messages": [{"role": "user", "content": req.message}]})
    try:
        _graph.invoke(None, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent error: {type(e).__name__}: {e}")

    reply, stage = _extract_reply(config)
    return ChatResponse(session_id=session_id, reply=reply, stage=stage)

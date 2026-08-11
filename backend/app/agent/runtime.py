"""
LangGraph 실행 wrapper.

그래프는 interrupt_before=["wait_for_input"] 로 컴파일되어 있어,
매 사용자 입력마다 아래 패턴으로 동작한다.

  [최초]
  1. ainvoke(초기 state, config)  → wait_for_input 직전에서 interrupt
  2. aupdate_state(config, {messages: [user_msg]})
  3. ainvoke(None, config)        → 그래프 실행 → 다음 wait_for_input 직전에서 interrupt

  [이후 메시지]
  1. aupdate_state(config, {messages: [user_msg]})
  2. ainvoke(None, config)        → 실행 → interrupt

thread_id = conversation_id 로 사용한다.
"""

import sys
import os
import uuid
import asyncio
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

# vendor 경로를 Python path에 추가
_VENDOR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../vendor/ddalangoo-langgraph")
)
if _VENDOR not in sys.path:
    # Keep the backend app directory ahead of vendor modules so uvicorn reload
    # continues to resolve backend/main.py for "main:app".
    sys.path.append(_VENDOR)

from langchain_core.messages import HumanMessage
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.graph.builder import build_graph
from src.state.schema import get_default_shopping_state

# asyncpg URL → psycopg3 conninfo 변환
_RAW_DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/ddalangoo")
_PG_CONNINFO = _RAW_DB_URL.replace("postgresql+asyncpg://", "postgresql://")

_graph = None
_pool: AsyncConnectionPool | None = None
_init_lock = asyncio.Lock()


async def init():
    """FastAPI lifespan startup: 풀 생성 + checkpoint 테이블 초기화 + 그래프 빌드."""
    global _graph, _pool
    # setup()은 CREATE INDEX CONCURRENTLY를 실행하므로 autocommit 단독 커넥션으로 처리
    async with AsyncPostgresSaver.from_conn_string(_PG_CONNINFO) as saver:
        await saver.setup()
    # 실제 운영은 커넥션 풀 기반 체크포인터 사용
    _pool = AsyncConnectionPool(_PG_CONNINFO, max_size=10, open=False)
    await _pool.open()
    checkpointer = AsyncPostgresSaver(_pool)
    _graph = build_graph(checkpointer=checkpointer)


async def ensure_initialized():
    """lifespan이 실행되지 않은 로컬 실행에서도 그래프를 한 번만 초기화한다."""
    if _graph is not None:
        return
    async with _init_lock:
        if _graph is None:
            await init()


async def shutdown():
    """FastAPI lifespan shutdown: 풀 종료."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_graph():
    if _graph is None:
        raise RuntimeError("runtime.init() 이 완료되기 전에 그래프가 호출되었습니다.")
    return _graph


def _config(conversation_id: int) -> dict:
    return {"configurable": {"thread_id": str(conversation_id)}}


async def update_state(conversation_id: int, patch: dict) -> dict:
    await ensure_initialized()
    graph = get_graph()
    config = _config(conversation_id)
    await graph.aupdate_state(config, patch)
    snapshot = await graph.aget_state(config)
    return snapshot.values


async def start(user_id: int, message: str, conversation_id: int) -> dict:
    """새 대화 시작. 그래프를 초기화하고 첫 메시지를 처리한다."""
    await ensure_initialized()
    graph = get_graph()
    config = _config(conversation_id)

    initial_state = get_default_shopping_state(
        user_id=str(user_id),
        session_id=str(uuid.uuid4()),
    )
    initial_state["conversation_id"] = conversation_id

    await graph.ainvoke(initial_state, config)
    await graph.aupdate_state(config, {"messages": [HumanMessage(content=message)]})
    await graph.ainvoke(None, config)

    snapshot = await graph.aget_state(config)
    return snapshot.values


async def resume(conversation_id: int, message: str) -> dict:
    """기존 대화에 메시지를 추가하고 그래프를 재개한다."""
    await ensure_initialized()
    graph = get_graph()
    config = _config(conversation_id)

    await graph.aupdate_state(config, {"messages": [HumanMessage(content=message)]})
    await graph.ainvoke(None, config)

    snapshot = await graph.aget_state(config)
    return snapshot.values


async def inject_and_resume(conversation_id: int, patch: dict) -> dict:
    """confirm_action 등 프론트가 직접 state 변경을 주입할 때 사용."""
    await ensure_initialized()
    graph = get_graph()
    config = _config(conversation_id)

    await graph.aupdate_state(config, patch)
    await graph.ainvoke(None, config)

    snapshot = await graph.aget_state(config)
    return snapshot.values

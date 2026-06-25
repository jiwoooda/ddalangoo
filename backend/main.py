from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# 공통 환경변수는 루트 .env에서 읽고, 백엔드 전용 값은 backend/.env가 덮어쓴다.
BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)
from fastapi.middleware.cors import CORSMiddleware
from app.routers import (
    agent, user, address, product,
    purchase_history, recommendation, order, payment,
    admin, dev, cart, voice
)
from app.agent import runtime
from app.core.migrations import run_migrations
from app.services import voice_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
    await voice_service.cleanup_tts_storage()
    await runtime.init()
    yield
    await runtime.shutdown()


app = FastAPI(title="Ddalangoo API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent.router, prefix="/api")
app.include_router(user.router, prefix="/api")
app.include_router(address.router, prefix="/api")
app.include_router(product.router, prefix="/api")
app.include_router(purchase_history.router, prefix="/api")
app.include_router(recommendation.router, prefix="/api")
app.include_router(order.router, prefix="/api")
app.include_router(payment.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(dev.router, prefix="/api")
app.include_router(cart.router, prefix="/api")
app.include_router(voice.router, prefix="/api")

_static_dir = Path(__file__).resolve().parent / "app" / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

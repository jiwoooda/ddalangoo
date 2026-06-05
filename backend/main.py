from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from app.routers import (
    agent, user, address, product,
    purchase_history, recommendation, order, payment,
    admin, dev, cart, voice
)
from app.agent import runtime
from app.core.migrations import run_migrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
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

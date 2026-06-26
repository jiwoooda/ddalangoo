from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import APP_ENV, DATABASE_URL


def _get_database_url() -> str:
    """DATABASE_URL이 없을 때 DB 연결 실패 원인을 명확히 보여준다."""
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 필요합니다. "
            "backend/.env.example를 참고해 backend/.env 또는 저장소 루트 .env에 설정하세요. "
            "예: DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/ddalangoo"
        )
    # Railway는 기본적으로 postgresql:// URL을 제공한다.
    # 앱은 SQLAlchemy async engine을 쓰므로 asyncpg 드라이버를 명시해야 한다.
    if DATABASE_URL.startswith("postgresql://"):
        return DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    return DATABASE_URL


# SQLAlchemy Async ORM에서 사용할 비동기 DB 엔진이다.
async_engine = create_async_engine(
    _get_database_url(),
    echo=APP_ENV == "development",
    pool_pre_ping=True,
)

# 요청마다 독립적인 AsyncSession을 만들기 위한 세션 팩토리다.
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Depends에서 사용할 DB 세션 의존성이다.

    사용 예:
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session

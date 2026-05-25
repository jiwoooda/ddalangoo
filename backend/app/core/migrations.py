import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"


async def run_migrations() -> None:
    """앱 startup 전에 Alembic migration을 최신 상태로 맞춘다."""

    def upgrade_head() -> None:
        # Alembic env.py 내부에서 async DB 연결을 만들기 때문에,
        # FastAPI 이벤트 루프 바깥 thread에서 동기 명령으로 실행한다.
        alembic_config = Config(str(ALEMBIC_INI_PATH))
        command.upgrade(alembic_config, "head")

    await asyncio.to_thread(upgrade_head)

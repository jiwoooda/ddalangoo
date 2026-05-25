import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

# Alembic은 앱 런타임과 별도로 실행되므로 여기서 직접 .env를 읽는다.
load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)

target_metadata = Base.metadata


def _database_url() -> str:
    """Alembic이 사용할 DATABASE_URL을 .env에서 읽는다."""
    from os import getenv

    database_url = getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL 환경변수가 필요합니다. "
            "예: postgresql+asyncpg://user:password@localhost:5432/ddalangoo"
        )
    return database_url


def run_migrations_offline() -> None:
    """DB 접속 없이 SQL 스크립트를 생성하는 offline migration 모드다."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Async connection 안에서 실제 Alembic migration을 실행한다."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """SQLAlchemy Async Engine으로 online migration을 실행한다."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

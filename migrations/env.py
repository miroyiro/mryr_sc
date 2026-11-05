"""Alembic 실행 설정 (async).

- DB 주소: settings.DATABASE_URL (.env)
- 버전 기록 테이블: miroyiro_scrap.alembic_version
- autogenerate 대상: miroyiro_scrap 스키마만 (main 테이블은 절대 건드리지 않음)
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from src.config.database import SCHEMA, Base
from src.config.settings import settings

# import src.models  # TODO: 모델 만들면 주석 해제 (autogenerate가 모델을 인식하도록)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """scrap 스키마 객체만 비교 대상으로 (main 스키마 무시)"""
    if type_ == "table":
        return obj.schema == SCHEMA
    return True


def _configure(connection=None, url=None):
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_object=include_object,
        literal_binds=url is not None,
    )


def run_migrations_offline() -> None:
    _configure(url=settings.DATABASE_URL)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # 버전 테이블이 이 스키마 안에 생기므로 먼저 만들어 둠
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    connection.execute(text(f"SET search_path TO {SCHEMA}, public"))
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.DATABASE_URL, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

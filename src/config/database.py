from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config.settings import settings

SCHEMA = "miroyiro_scrap"

# 커넥션 풀을 가진 엔진. search_path = 테이블명만 쓰면 scrap 스키마에서 찾음
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    pool_pre_ping=True,  # 미니PC 재부팅·네트워크 끊김 뒤 죽은 커넥션 자동 교체
    connect_args={
        "server_settings": {
            "search_path": f"{SCHEMA},public",
            "timezone": "Asia/Seoul",              # TIMESTAMPTZ 출력이 +09:00
            "application_name": "miroyiro-scrap",  # pg_stat_activity 에서 누가 연결했는지 보임
        }
    },
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db():
    """FastAPI Depends용: 요청마다 세션을 빌려주고 끝나면 반납. commit 은 라우터/서비스에서 명시적으로."""
    async with SessionLocal() as session:
        yield session


class Base(DeclarativeBase):
    """모든 모델의 부모. 스키마는 여기서 한 번만 지정 (migrations/env.py 가 이 metadata 를 봄)"""

    metadata = MetaData(schema=SCHEMA)

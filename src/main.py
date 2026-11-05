from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api import health
from src.config.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # TODO: 스케줄러 시작 (scheduler/)
    yield
    # TODO: 스케줄러 정지
    await engine.dispose()


app = FastAPI(title="miroyiro-scrap", lifespan=lifespan)

# ── 라우터 등록: 각자 PR에서 한 줄씩만 추가 (충돌 방지) ──
app.include_router(health.router)

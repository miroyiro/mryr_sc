"""miroyiro-scrap FastAPI 엔트리 (공통 파일 — 명주 소유). 실행: uvicorn src.main:app --port 8000

라우터 등록 규칙 (충돌 방지): 한 줄씩, 알파벳 순. 준현 라우터가 생기면 INTERNAL_ROUTERS 에 한 줄 추가 PR.
/internal/* 는 전부 X-Internal-Key 필수 (라우터 단위가 아니라 등록 시 한 번에 → 빠뜨릴 수 없음).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from src.api import (
    cache, health, job, pipeline_error, processed_item, raw_item, resolve, schedule, source, sync, target,
)
from src.admin import auth_router as admin_auth
from src.admin import read_router as admin_read
from src.admin import web as admin_web
from src.admin import write_router as admin_write
from src.api.deps import require_internal_key
from src.clients.backend_client import close_backend
from src.config.database import engine
from src.config.settings import settings

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("miroyiro-scrap")

INTERNAL_ROUTERS = [   # 경로는 api문서(노션) 기준                     # /internal/kopis/sync
    cache.router,                       # /internal/cache
    job.router,                         # /internal/pipeline/jobs
    job.stats_router,                   # /internal/pipeline/stats
    pipeline_error.router,              # /internal/pipeline/errors
    processed_item.candidates_router,   # /internal/events/candidates
    processed_item.review_router,       # /internal/pipeline/review
    processed_item.router,              # /internal/pipeline/processedItems
    raw_item.router,                    # /internal/pipeline/rawItems
    resolve.router,                     # /internal/anilist
    schedule.router,                    # /internal/pipeline/schedules
    source.router,                      # /internal/pipeline/sources
    sync.router,                        # /internal/{anissia,kopis,aniplus/*}/sync
    target.router,                      # /internal/pipeline/targets
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SCHEDULER_ENABLED:
        from src.scheduler import scheduler as sched
        from src.scheduler.jobs import resume_stale_jobs
        await sched.start()
        sched.scheduler.add_job(resume_stale_jobs, id="resume_stale_jobs", replace_existing=True)  # 1회
    log.info("miroyiro-scrap started (env=%s, scheduler=%s)", settings.APP_ENV, settings.SCHEDULER_ENABLED)
    yield
    # graceful shutdown: 새 잡 멈추기 → 외부 클라이언트 닫기 → DB 풀 닫기
    if settings.SCHEDULER_ENABLED:
        from src.scheduler import scheduler as sched
        sched.stop()
    await close_backend()
    await engine.dispose()


app = FastAPI(
    title="miroyiro-scrap",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None if settings.is_prod else "/docs",   # 운영에선 문서 숨김
    redoc_url=None,
)

app.include_router(health.router)
# 관리 GUI: /admin/** 만. internal 키 대신 세션·CSRF·역할 (src/admin/deps.py). 공개 프록시는 /admin·/health 만 통과
app.include_router(admin_auth.router)
app.include_router(admin_read.router)
app.include_router(admin_write.router)
admin_web.install(app)   # /admin 화면·보안 헤더·/admin 500 고정 JSON
for r in INTERNAL_ROUTERS:
    app.include_router(r, dependencies=[Depends(require_internal_key)])


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError):
    """DB 제약(CHECK/UNIQUE) 위반이 라우터에서 안 잡히고 올라오면 500 대신 400/409."""
    msg = str(exc.orig) if exc.orig else str(exc)
    code = status.HTTP_409_CONFLICT if "unique" in msg.lower() else status.HTTP_400_BAD_REQUEST
    return JSONResponse(status_code=code, content={"detail": "constraint violation"})

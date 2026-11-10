"""소스별 동기화 — api문서 '수집/API', '수집/스크래핑' 행.

  POST /internal/anissia/sync            {weeks?}                 (준현 컬렉터)
  POST /internal/kopis/sync              {afterdate?, shcate?}    (준현 컬렉터)
  POST /internal/aniplus/news/sync                                (명주, sitemap)
  POST /internal/aniplus/simulcast/sync  {season?, season_year?}  (명주, Playwright)
  (AniList 는 리졸버라 api/resolve.py 의 /internal/anilist/sync)

공통 규칙 'sync 는 202' → 잡만 큐에 넣고 job id 반환. 결과는 GET /internal/pipeline/jobs/{id}.
"""
from fastapi import APIRouter, BackgroundTasks, status

from src.api.deps import SessionDep, not_found
from src.models.enums import TargetType
from src.schemas.common import DataResponse
from src.schemas.sync import AnissiaSyncRequest, KopisSyncRequest, SeasonSyncRequest, SyncQueuedOut
from src.services.collect_service import run_scrape_job
from src.services.sync_service import SourceNotFound, enqueue_source

router = APIRouter(prefix="/internal", tags=["sync"])


async def _enqueue(session, bg: BackgroundTasks, source: str, *, target_type=None, params=None) -> SyncQueuedOut:
    try:
        job_ids = await enqueue_source(session, source, target_type=target_type, params=params)
    except SourceNotFound as exc:
        raise not_found(f"source '{source}'") from exc
    await session.commit()
    for job_id in job_ids:
        bg.add_task(run_scrape_job, job_id)
    return SyncQueuedOut(source=source, job_ids=job_ids)


@router.post("/anissia/sync", response_model=DataResponse[SyncQueuedOut], status_code=status.HTTP_202_ACCEPTED)
async def anissia_sync(session: SessionDep, bg: BackgroundTasks, body: AnissiaSyncRequest | None = None):
    params = body.model_dump() if body else None
    return DataResponse(data=await _enqueue(session, bg, "anissia", params=params))


@router.post("/kopis/sync", response_model=DataResponse[SyncQueuedOut], status_code=status.HTTP_202_ACCEPTED)
async def kopis_sync(session: SessionDep, bg: BackgroundTasks, body: KopisSyncRequest | None = None):
    params = body.model_dump() if body else None
    return DataResponse(data=await _enqueue(session, bg, "kopis", params=params))


@router.post("/aniplus/news/sync", response_model=DataResponse[SyncQueuedOut],
             status_code=status.HTTP_202_ACCEPTED)
async def aniplus_news_sync(session: SessionDep, bg: BackgroundTasks):
    return DataResponse(data=await _enqueue(session, bg, "aniplus", target_type=TargetType.SITEMAP))


@router.post("/aniplus/simulcast/sync", response_model=DataResponse[SyncQueuedOut],
             status_code=status.HTTP_202_ACCEPTED)
async def aniplus_simulcast_sync(session: SessionDep, bg: BackgroundTasks, body: SeasonSyncRequest | None = None):
    params = body.model_dump() if body else None
    return DataResponse(data=await _enqueue(session, bg, "aniplus", target_type=TargetType.SPA_PAGE, params=params))

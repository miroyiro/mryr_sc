"""/internal/pipeline/jobs, /internal/pipeline/stats — api문서 '파이프라인' 기준.

문서 행: POST jobs(202) · GET jobs/{id} · POST jobs/{id}/retry(202, failed 아니면 409) · GET stats
문서에 추가한 행: GET jobs(목록) · POST jobs/{id}/cancel · POST jobs/{id}/process(재가공, 202)
"""
from datetime import datetime, time

from fastapi import APIRouter, BackgroundTasks, Query, status

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.models.enums import ScrapeJobStatus
from src.repositories import job_repository, source_repository, target_repository
from src.schemas.common import DataResponse, ListResponse, QueuedOut
from src.schemas.job import JobCreate, JobOut, StatsOut, StatsToday
from src.services.collect_service import run_scrape_job
from src.services.process_service import run_process_for_scrape_job
from src.utils.time import KST, now_kst

router = APIRouter(prefix="/internal/pipeline/jobs", tags=["pipeline:job"])
stats_router = APIRouter(prefix="/internal/pipeline/stats", tags=["pipeline:stats"])


@router.get("", response_model=ListResponse[JobOut])
async def list_jobs(
    session: SessionDep, page: PageDep,
    status_: ScrapeJobStatus | None = Query(None, alias="status"),
    source_id: int | None = Query(None, alias="sourceId"),
):
    items, total = await job_repository.list_scrape_jobs(session, page, status=status_, source_id=source_id)
    return ListResponse(data=items, meta=meta(page, total))


@router.get("/{id}", response_model=DataResponse[JobOut])
async def get_job(id: int, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    job = await job_repository.get_scrape_job(session, id)
    if job is None:
        raise not_found("job")
    return DataResponse(data=job)


@router.post("", response_model=DataResponse[JobOut], status_code=status.HTTP_202_ACCEPTED)
async def create_job(body: JobCreate, session: SessionDep, bg: BackgroundTasks):
    """수동 실행. 소스가 꺼져 있어도 관리자 테스트용으로 허용 (대상은 검증된 것만 — collect_service 가 검사)."""
    if await source_repository.get(session, body.source_id) is None:
        raise not_found("source")
    target = await target_repository.get(session, body.target_id) if body.target_id else None
    if body.target_id and target is None:
        raise not_found("target")
    job = await job_repository.create_scrape_job(
        session, source_id=body.source_id, target_id=body.target_id,
        target=body.target or (target.value if target else None),
    )
    await session.commit()
    bg.add_task(run_scrape_job, job.id)
    return DataResponse(data=job)


@router.post("/{id}/retry", response_model=DataResponse[JobOut], status_code=status.HTTP_202_ACCEPTED)
async def retry_job(id: int, session: SessionDep, bg: BackgroundTasks):  # noqa: A002
    old = await job_repository.get_scrape_job(session, id)
    if old is None:
        raise not_found("job")
    if old.status != ScrapeJobStatus.FAILED:
        raise conflict("failed 작업만 재시도할 수 있음")
    job = await job_repository.create_scrape_job(
        session, source_id=old.source_id, target_id=old.target_id, retry_of=old.id, target=old.target
    )
    await session.commit()
    bg.add_task(run_scrape_job, job.id)
    return DataResponse(data=job)


@router.post("/{id}/cancel", response_model=DataResponse[JobOut])
async def cancel_job(id: int, session: SessionDep):  # noqa: A002
    """running 중 취소는 '표시'만 — 끝날 때 조건부 UPDATE 가 cancelled 를 덮어쓰지 않음."""
    if await job_repository.get_scrape_job(session, id) is None:
        raise not_found("job")
    if not await job_repository.cancel_scrape_job(session, id):
        raise conflict("이미 끝난 작업")
    await session.commit()
    job = await job_repository.get_scrape_job(session, id)
    await session.refresh(job)
    return DataResponse(data=job)


@router.post("/{id}/process", response_model=DataResponse[QueuedOut], status_code=status.HTTP_202_ACCEPTED)
async def reprocess_job(id: int, session: SessionDep, bg: BackgroundTasks):  # noqa: A002
    """파서 고친 뒤 이 잡에서 들어온 raw 를 다시 가공 (pending 만 덮어씀, 승인·반려된 건 보존)."""
    if await job_repository.get_scrape_job(session, id) is None:
        raise not_found("job")
    bg.add_task(run_process_for_scrape_job, id)
    return DataResponse(data=QueuedOut(job_ids=[id]))


@stats_router.get("", response_model=DataResponse[StatsOut])
async def stats(session: SessionDep):
    """오늘(KST 0시~) 수집·가공 합계."""
    start = datetime.combine(now_kst().date(), time(0, 0), KST)
    s = await job_repository.stats_since(session, start)
    return DataResponse(data=StatsOut(today=StatsToday(**s)))

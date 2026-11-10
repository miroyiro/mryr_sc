"""/internal/pipeline/jobs — scrape_job 조회·수동 실행·재시도·취소 (명주).
큐 접수 = 202 (나중에 처리), 취소 = 200, 이미 끝난 잡 취소/진행 중 재시도 = 409 (06 규칙)."""
from fastapi import APIRouter, BackgroundTasks, Query, status

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.models.enums import ScrapeJobStatus
from src.repositories import job_repository, source_repository, target_repository
from src.schemas.common import ListResponse, QueuedResponse
from src.schemas.job import JobCreate, JobOut
from src.services.collect_service import run_scrape_job
from src.services.process_service import run_process_for_scrape_job

router = APIRouter(prefix="/internal/pipeline/jobs", tags=["pipeline:job"])


@router.get("", response_model=ListResponse[JobOut])
async def list_jobs(
    session: SessionDep, page: PageDep,
    status_: ScrapeJobStatus | None = Query(None, alias="status"),
    source_id: int | None = Query(None, alias="sourceId"),
):
    items, total = await job_repository.list_scrape_jobs(session, page, status=status_, source_id=source_id)
    return ListResponse(items=items, meta=meta(page, total))


@router.get("/{jobId}", response_model=JobOut)
async def get_job(jobId: int, session: SessionDep):  # noqa: N803
    job = await job_repository.get_scrape_job(session, jobId)
    if job is None:
        raise not_found("job")
    return job


@router.post("", response_model=QueuedResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_job(body: JobCreate, session: SessionDep, bg: BackgroundTasks):
    """수동 실행. 소스가 꺼져 있어도 관리자 테스트용으로 허용 (단, 대상은 검증된 것만 — collect_service 가 검사)."""
    if await source_repository.get(session, body.source_id) is None:
        raise not_found("source")
    target = await target_repository.get(session, body.target_id) if body.target_id else None
    if body.target_id and target is None:
        raise not_found("target")
    job = await job_repository.create_scrape_job(
        session, source_id=body.source_id, target_id=body.target_id, target=target.value if target else None
    )
    await session.commit()
    bg.add_task(run_scrape_job, job.id)
    return QueuedResponse(job_id=job.id)


@router.post("/{jobId}/retry", response_model=QueuedResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_job(jobId: int, session: SessionDep, bg: BackgroundTasks):  # noqa: N803
    old = await job_repository.get_scrape_job(session, jobId)
    if old is None:
        raise not_found("job")
    if not ScrapeJobStatus(old.status).is_finished:
        raise conflict("job is still queued/running")
    job = await job_repository.create_scrape_job(
        session, source_id=old.source_id, target_id=old.target_id, retry_of=old.id, target=old.target
    )
    await session.commit()
    bg.add_task(run_scrape_job, job.id)
    return QueuedResponse(job_id=job.id)


@router.post("/{jobId}/cancel", response_model=JobOut)
async def cancel_job(jobId: int, session: SessionDep):  # noqa: N803
    """running 중 취소는 '표시'만 (진행 중 코루틴을 강제로 죽이진 않음 — 다음 단계에서 확인)."""
    if await job_repository.get_scrape_job(session, jobId) is None:
        raise not_found("job")
    if not await job_repository.cancel_scrape_job(session, jobId):
        raise conflict("job already finished")
    await session.commit()
    return await job_repository.get_scrape_job(session, jobId)


@router.post("/{jobId}/process", response_model=QueuedResponse, status_code=status.HTTP_202_ACCEPTED)
async def reprocess_job(jobId: int, session: SessionDep, bg: BackgroundTasks):  # noqa: N803
    """파서 고친 뒤 같은 raw 를 다시 가공 (pending 만 덮어씀)."""
    if await job_repository.get_scrape_job(session, jobId) is None:
        raise not_found("job")
    bg.add_task(run_process_for_scrape_job, jobId)
    return QueuedResponse(job_id=jobId)

"""/internal/pipeline/errors — api문서: GET 목록. 문서에 추가: PATCH /{id}(상태 변경) · POST /{id}/retry(202)."""
from fastapi import APIRouter, BackgroundTasks, Query, status

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.models.enums import ErrorJobType, ErrorStatus
from src.repositories import error_repository, job_repository
from src.schemas.common import DataResponse, ListResponse, QueuedOut
from src.schemas.error import ErrorOut, ErrorUpdate
from src.services.collect_service import run_scrape_job
from src.utils.time import now_kst

router = APIRouter(prefix="/internal/pipeline/errors", tags=["pipeline:error"])


@router.get("", response_model=ListResponse[ErrorOut])
async def list_errors(
    session: SessionDep, page: PageDep,
    status_: ErrorStatus | None = Query(None, alias="status"),
    job_type: ErrorJobType | None = Query(None, alias="jobType"),
    job_id: int | None = Query(None, alias="jobId"),
):
    items, total = await error_repository.list_(session, page, status=status_, job_type=job_type, job_id=job_id)
    return ListResponse(data=items, meta=meta(page, total))


@router.patch("/{id}", response_model=DataResponse[ErrorOut])
async def update_error(id: int, body: ErrorUpdate, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    err = await error_repository.get(session, id)
    if err is None:
        raise not_found("error")
    await error_repository.set_status(session, err, body.status, at=now_kst())
    await session.commit()
    return DataResponse(data=err)


@router.post("/{id}/retry", response_model=DataResponse[QueuedOut], status_code=status.HTTP_202_ACCEPTED)
async def retry_from_error(id: int, session: SessionDep, bg: BackgroundTasks):  # noqa: A002 — 문서 경로 변수 {id}
    """scrape 에러 → 같은 소스/대상으로 새 잡 (retry_of 연결). process 에러는 jobs/{id}/process 사용."""
    err = await error_repository.get(session, id)
    if err is None:
        raise not_found("error")
    if err.job_type != ErrorJobType.SCRAPE:
        raise conflict("process 에러는 /internal/pipeline/jobs/{id}/process 로 재가공")
    old = await job_repository.get_scrape_job(session, err.job_id)
    if old is None:
        raise not_found("job")
    job = await job_repository.create_scrape_job(
        session, source_id=old.source_id, target_id=old.target_id, retry_of=old.id, target=old.target
    )
    await error_repository.bump_retry(session, err)
    await session.commit()
    bg.add_task(run_scrape_job, job.id)
    return DataResponse(data=QueuedOut(job_ids=[job.id]))

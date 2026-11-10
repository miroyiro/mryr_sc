"""scrape_job / process_job DB 함수. (03 문서에 담당 미배정 → 파이프라인 api 소유자인 명주가 맡는 안)"""
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ProcessJob, ScrapeJob
from src.models.enums import ProcessJobStatus, ScrapeJobStatus
from src.repositories.base import paginate
from src.schemas.common import PageParams
from src.utils.time import now_kst


# ---------- scrape_job ----------
async def create_scrape_job(
    session: AsyncSession, *, source_id: int, target_id: int | None = None,
    schedule_id: int | None = None, retry_of: int | None = None, target: str | None = None,
) -> ScrapeJob:
    job = ScrapeJob(source_id=source_id, target_id=target_id, schedule_id=schedule_id,
                    retry_of=retry_of, target=target, status=ScrapeJobStatus.QUEUED)
    session.add(job)
    await session.flush()
    return job


async def get_scrape_job(session: AsyncSession, job_id: int) -> ScrapeJob | None:
    return await session.get(ScrapeJob, job_id)


async def list_scrape_jobs(
    session: AsyncSession, page: PageParams, *, status: ScrapeJobStatus | None = None,
    source_id: int | None = None,
) -> tuple[list[ScrapeJob], int]:
    stmt = select(ScrapeJob).order_by(ScrapeJob.created_at.desc())
    if status is not None:
        stmt = stmt.where(ScrapeJob.status == status)
    if source_id is not None:
        stmt = stmt.where(ScrapeJob.source_id == source_id)
    return await paginate(session, stmt, page)


async def claim_scrape_job(session: AsyncSession, job_id: int) -> bool:
    """queued → running 을 '조건부 UPDATE'로. 두 워커가 같은 잡을 잡아도 한 명만 성공 (Lost Update 방지)."""
    result = await session.execute(
        update(ScrapeJob)
        .where(ScrapeJob.id == job_id, ScrapeJob.status == ScrapeJobStatus.QUEUED)
        .values(status=ScrapeJobStatus.RUNNING, started_at=now_kst())
    )
    return result.rowcount == 1


async def finish_scrape_job(
    session: AsyncSession, job_id: int, *, status: ScrapeJobStatus, error_message: str | None = None
) -> bool:
    """running → completed/failed 도 조건부 UPDATE. 실행 중에 관리자가 cancel 했으면 덮어쓰지 않음 (False)."""
    result = await session.execute(
        update(ScrapeJob)
        .where(ScrapeJob.id == job_id, ScrapeJob.status == ScrapeJobStatus.RUNNING)
        .values(status=status, finished_at=now_kst(), error_message=error_message)
    )
    return result.rowcount == 1


async def cancel_scrape_job(session: AsyncSession, job_id: int) -> bool:
    """끝난 잡은 취소 불가 → False (라우터에서 409)."""
    result = await session.execute(
        update(ScrapeJob)
        .where(ScrapeJob.id == job_id,
               ScrapeJob.status.in_([ScrapeJobStatus.QUEUED, ScrapeJobStatus.RUNNING]))
        .values(status=ScrapeJobStatus.CANCELLED, finished_at=now_kst())
    )
    return result.rowcount == 1


async def list_stale_queued(session: AsyncSession, limit: int = 50) -> list[ScrapeJob]:
    """서버 재시작으로 버려진 queued 잡 (시작 시 다시 실행)."""
    stmt = select(ScrapeJob).where(ScrapeJob.status == ScrapeJobStatus.QUEUED).order_by(ScrapeJob.id).limit(limit)
    return list((await session.scalars(stmt)).all())


# ---------- process_job ----------
async def create_process_job(session: AsyncSession, *, scrape_job_id: int | None) -> ProcessJob:
    job = ProcessJob(scrape_job_id=scrape_job_id, status=ProcessJobStatus.QUEUED)
    session.add(job)
    await session.flush()
    return job


async def get_process_job(session: AsyncSession, job_id: int) -> ProcessJob | None:
    return await session.get(ProcessJob, job_id)


async def stats_since(session: AsyncSession, since) -> dict[str, int]:
    """GET /internal/pipeline/stats — since 이후 생성된 잡 합계."""
    s = (await session.execute(
        select(
            func.coalesce(func.sum(ScrapeJob.total_count), 0),
            func.coalesce(func.sum(ScrapeJob.collected_count), 0),
            func.coalesce(func.sum(ScrapeJob.duplicate_count), 0),
        ).where(ScrapeJob.created_at >= since)
    )).one()
    p = (await session.execute(
        select(
            func.coalesce(func.sum(ProcessJob.processed_count), 0),
            func.coalesce(func.sum(ProcessJob.failed_count), 0),
        ).where(ProcessJob.created_at >= since)
    )).one()
    return {"scraped": int(s[0]), "new": int(s[1]), "duplicate": int(s[2]),
            "processed": int(p[0]), "failed": int(p[1])}

"""scrape_error DB 함수 (명주). 파이프라인 어디서 실패하든 여기에 한 줄 남긴다."""
import traceback
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ScrapeError
from src.models.enums import ErrorJobType, ErrorStatus
from src.repositories.base import paginate
from src.schemas.common import PageParams


async def record(
    session: AsyncSession,
    *,
    job_type: ErrorJobType,
    job_id: int,
    error_type: str,
    exc: BaseException | None = None,
    message: str | None = None,
    raw_item_id: int | None = None,
) -> ScrapeError:
    err = ScrapeError(
        job_type=job_type,
        job_id=job_id,
        raw_item_id=raw_item_id,
        type=error_type[:50],
        message=(message or (repr(exc) if exc else "unknown"))[:1000],
        stack="".join(traceback.format_exception(exc)) if exc else None,
    )
    session.add(err)
    await session.flush()
    return err


async def get(session: AsyncSession, error_id: int) -> ScrapeError | None:
    return await session.get(ScrapeError, error_id)


async def list_(
    session: AsyncSession,
    page: PageParams,
    *,
    status: ErrorStatus | None = None,
    job_type: ErrorJobType | None = None,
    job_id: int | None = None,
) -> tuple[list[ScrapeError], int]:
    stmt = select(ScrapeError).order_by(ScrapeError.created_at.desc())
    if status is not None:
        stmt = stmt.where(ScrapeError.status == status)
    if job_type is not None:
        stmt = stmt.where(ScrapeError.job_type == job_type)
    if job_id is not None:
        stmt = stmt.where(ScrapeError.job_id == job_id)
    return await paginate(session, stmt, page)


async def set_status(session: AsyncSession, err: ScrapeError, status: ErrorStatus, *, at: datetime) -> None:
    err.status = status
    err.resolved_at = at if status != ErrorStatus.UNRESOLVED else None


async def bump_retry(session: AsyncSession, err: ScrapeError) -> None:
    err.retry_count += 1

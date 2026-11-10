"""scrape_schedule DB 함수 — ⚠️ 준현 소유 파일 (03 분담표).
api/schedule.py·scheduler/loader.py 가 쓰는 '인터페이스 합의용 최소 stub'. 준현이 채우거나 고쳐서 PR.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ScrapeSchedule, ScrapeSource
from src.repositories.base import paginate
from src.schemas.common import PageParams


async def get(session: AsyncSession, schedule_id: int) -> ScrapeSchedule | None:
    return await session.get(ScrapeSchedule, schedule_id)


async def list_(session: AsyncSession, page: PageParams, *, source_id: int | None = None) -> tuple[list[ScrapeSchedule], int]:
    stmt = select(ScrapeSchedule).order_by(ScrapeSchedule.id)
    if source_id is not None:
        stmt = stmt.where(ScrapeSchedule.source_id == source_id)
    return await paginate(session, stmt, page)


async def list_runnable(session: AsyncSession) -> list[ScrapeSchedule]:
    """스케줄 enabled AND 소스 enabled 인 것만 (소스를 끄면 스케줄도 멈춤)."""
    stmt = (
        select(ScrapeSchedule)
        .join(ScrapeSource, ScrapeSource.id == ScrapeSchedule.source_id)
        .where(ScrapeSchedule.enabled.is_(True), ScrapeSource.enabled.is_(True))
    )
    return list((await session.scalars(stmt)).all())


async def create(session: AsyncSession, **fields) -> ScrapeSchedule:
    schedule = ScrapeSchedule(**fields)
    session.add(schedule)
    await session.flush()
    return schedule


async def mark_run(session: AsyncSession, schedule: ScrapeSchedule, *, at: datetime,
                   next_run_at: datetime | None) -> None:
    schedule.last_run_at = at
    schedule.next_run_at = next_run_at


async def delete(session: AsyncSession, schedule: ScrapeSchedule) -> None:
    await session.delete(schedule)

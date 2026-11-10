"""scrape_target DB 함수 (명주). 수집은 is_verified + active 인 대상만."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ScrapeTarget
from src.models.enums import TargetStatus
from src.repositories.base import paginate
from src.schemas.common import PageParams


async def get(session: AsyncSession, target_id: int) -> ScrapeTarget | None:
    return await session.get(ScrapeTarget, target_id)


async def list_(
    session: AsyncSession,
    page: PageParams,
    *,
    source_id: int | None = None,
    verified: bool | None = None,
    status: TargetStatus | None = None,
) -> tuple[list[ScrapeTarget], int]:
    stmt = select(ScrapeTarget).order_by(ScrapeTarget.id.desc())
    if source_id is not None:
        stmt = stmt.where(ScrapeTarget.source_id == source_id)
    if verified is not None:
        stmt = stmt.where(ScrapeTarget.is_verified.is_(verified))
    if status is not None:
        stmt = stmt.where(ScrapeTarget.status == status)
    return await paginate(session, stmt, page)


async def list_collectable(session: AsyncSession, source_id: int) -> list[ScrapeTarget]:
    """스케줄러가 쓰는 '지금 수집해도 되는 대상'."""
    stmt = select(ScrapeTarget).where(
        ScrapeTarget.source_id == source_id,
        ScrapeTarget.is_verified.is_(True),
        ScrapeTarget.status == TargetStatus.ACTIVE,
    )
    return list((await session.scalars(stmt)).all())


async def find_by_value(session: AsyncSession, source_id: int, value: str) -> ScrapeTarget | None:
    stmt = select(ScrapeTarget).where(ScrapeTarget.source_id == source_id, ScrapeTarget.value == value)
    return await session.scalar(stmt)


async def create(session: AsyncSession, **fields) -> ScrapeTarget:
    target = ScrapeTarget(**fields, is_verified=False)
    session.add(target)
    await session.flush()  # id 채우기
    return target


async def mark_crawled(
    session: AsyncSession, target: ScrapeTarget, *, at: datetime, last_seen_external_id: str | None
) -> None:
    target.last_crawled_at = at
    if last_seen_external_id:
        target.last_seen_external_id = last_seen_external_id


async def mark_broken(session: AsyncSession, target: ScrapeTarget) -> None:
    """구조 변경 등으로 연속 실패 → broken. 관리자가 확인 후 active 로."""
    target.status = TargetStatus.BROKEN


async def delete(session: AsyncSession, target: ScrapeTarget) -> None:
    await session.delete(target)

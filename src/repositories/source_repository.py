"""scrape_source DB 함수 — ⚠️ 준현 소유 파일 (03 분담표).
여기는 api/source.py·스케줄러가 쓰는 '인터페이스 합의용 최소 stub'. 준현이 이 시그니처대로 채우거나 고쳐서 PR.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ScrapeSource
from src.repositories.base import paginate
from src.schemas.common import PageParams


async def get(session: AsyncSession, source_id: int) -> ScrapeSource | None:
    return await session.get(ScrapeSource, source_id)


async def get_by_name(session: AsyncSession, name: str) -> ScrapeSource | None:
    return await session.scalar(select(ScrapeSource).where(ScrapeSource.name == name))


async def list_(session: AsyncSession, page: PageParams, *, enabled: bool | None = None) -> tuple[list[ScrapeSource], int]:
    stmt = select(ScrapeSource).order_by(ScrapeSource.id)
    if enabled is not None:
        stmt = stmt.where(ScrapeSource.enabled.is_(enabled))
    return await paginate(session, stmt, page)


async def create(session: AsyncSession, **fields) -> ScrapeSource:
    source = ScrapeSource(**fields)
    session.add(source)
    await session.flush()
    return source

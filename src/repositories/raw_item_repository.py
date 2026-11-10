"""raw_item DB 함수. (담당 미배정 → 명주 안)

중복 처리 2단계:
  1) UNIQUE(source_id, external_id)  → 같은 글은 한 행 (INSERT … ON CONFLICT)
  2) hash                            → 같은 글인데 내용이 바뀌었는지 (바뀌면 UPDATE + 재처리)
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ProcessedItem, RawItem
from src.repositories.base import paginate
from src.schemas.common import PageParams


@dataclass(slots=True)
class UpsertResult:
    raw_item_id: int
    inserted: bool   # 새 글
    changed: bool    # 기존 글인데 hash 바뀜


async def upsert(session: AsyncSession, *, source_id: int, scrape_job_id: int, external_id: str,
                 hash_: str, **fields) -> UpsertResult:
    existing = await session.scalar(
        select(RawItem).where(RawItem.source_id == source_id, RawItem.external_id == external_id)
    )
    if existing is None:
        stmt = (
            insert(RawItem)
            .values(source_id=source_id, scrape_job_id=scrape_job_id, external_id=external_id, hash=hash_, **fields)
            .on_conflict_do_nothing(constraint="uq_raw_external")  # 동시 수집 경쟁 대비
            .returning(RawItem.id)
        )
        new_id = await session.scalar(stmt)
        if new_id is not None:
            return UpsertResult(new_id, inserted=True, changed=False)
        existing = await session.scalar(
            select(RawItem).where(RawItem.source_id == source_id, RawItem.external_id == external_id)
        )
    if existing.hash != hash_:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.hash = hash_
        existing.scrape_job_id = scrape_job_id
        return UpsertResult(existing.id, inserted=False, changed=True)
    return UpsertResult(existing.id, inserted=False, changed=False)


async def get(session: AsyncSession, raw_item_id: int) -> RawItem | None:
    return await session.get(RawItem, raw_item_id)


async def list_(session: AsyncSession, page: PageParams, *, source_id: int | None = None,
                scrape_job_id: int | None = None) -> tuple[list[RawItem], int]:
    stmt = select(RawItem).order_by(RawItem.collected_at.desc())
    if source_id is not None:
        stmt = stmt.where(RawItem.source_id == source_id)
    if scrape_job_id is not None:
        stmt = stmt.where(RawItem.scrape_job_id == scrape_job_id)
    return await paginate(session, stmt, page)


async def list_unprocessed(session: AsyncSession, *, scrape_job_id: int | None = None,
                           limit: int = 500) -> list[RawItem]:
    """아직 processed_item 이 없는 raw (LEFT JOIN … IS NULL)."""
    stmt = (
        select(RawItem)
        .outerjoin(ProcessedItem, ProcessedItem.raw_item_id == RawItem.id)
        .where(ProcessedItem.id.is_(None))
        .order_by(RawItem.id)
        .limit(limit)
    )
    if scrape_job_id is not None:
        stmt = stmt.where(RawItem.scrape_job_id == scrape_job_id)
    return list((await session.scalars(stmt)).all())

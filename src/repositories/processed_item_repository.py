"""processed_item DB 함수. (담당 미배정 → 명주 안) 검수 대기열 + 팝업 후보 큐."""
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ProcessedItem
from src.models.enums import ProcessedCategory, ProcessedStatus
from src.repositories.base import paginate
from src.schemas.common import PageParams
from src.utils.time import now_kst


async def upsert_for_raw(session: AsyncSession, *, raw_item_id: int, process_job_id: int | None,
                         values: dict[str, Any]) -> int:
    """raw 1건 = processed 1건 (uq_processed_raw). 재처리면 UPDATE.
    단, 이미 published/rejected 된 건 덮어쓰지 않음 (검수 결과 보존)."""
    stmt = insert(ProcessedItem).values(raw_item_id=raw_item_id, process_job_id=process_job_id, **values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_processed_raw",
        set_={**{k: stmt.excluded[k] for k in values}, "process_job_id": stmt.excluded.process_job_id},
        where=ProcessedItem.status == ProcessedStatus.PENDING,
    ).returning(ProcessedItem.id)
    item_id = await session.scalar(stmt)
    if item_id is None:  # published/rejected 라서 UPDATE 안 됨
        item_id = await session.scalar(select(ProcessedItem.id).where(ProcessedItem.raw_item_id == raw_item_id))
    return int(item_id)


async def get(session: AsyncSession, item_id: int, *, for_update: bool = False) -> ProcessedItem | None:
    stmt = select(ProcessedItem).where(ProcessedItem.id == item_id)
    if for_update:
        stmt = stmt.with_for_update()  # 두 관리자가 동시에 승인 눌러도 한 명만
    return await session.scalar(stmt)


async def list_(session: AsyncSession, page: PageParams, *, status: ProcessedStatus | None = None,
                category: ProcessedCategory | None = None) -> tuple[list[ProcessedItem], int]:
    stmt = select(ProcessedItem).order_by(ProcessedItem.created_at.desc())
    if status is not None:
        stmt = stmt.where(ProcessedItem.status == status)
    if category is not None:
        stmt = stmt.where(ProcessedItem.category == category)
    return await paginate(session, stmt, page)


async def mark_published(session: AsyncSession, item: ProcessedItem, *, reviewed_by: int | None,
                         event_id: int | None, news_id: int | None) -> None:
    item.status = ProcessedStatus.PUBLISHED
    item.reviewed_by = reviewed_by
    item.reviewed_at = now_kst()
    item.published_event_id = event_id
    item.published_news_id = news_id


async def mark_rejected(session: AsyncSession, item_id: int, *, reviewed_by: int, reason: str) -> bool:
    result = await session.execute(
        update(ProcessedItem)
        .where(ProcessedItem.id == item_id, ProcessedItem.status == ProcessedStatus.PENDING)
        .values(status=ProcessedStatus.REJECTED, reviewed_by=reviewed_by,
                reviewed_at=now_kst(), reject_reason=reason)
    )
    return result.rowcount == 1

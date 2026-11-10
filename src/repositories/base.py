"""리포지토리 공통 도우미. 리포지토리 = 'DB 함수 모음'. commit 은 호출한 쪽(서비스/라우터)이 한다.
(트랜잭션 경계를 한 곳에서 정해야 여러 리포지토리 호출을 한 트랜잭션으로 묶을 수 있음)"""
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.common import PageParams

M = TypeVar("M")


async def paginate(session: AsyncSession, stmt: Select, page: PageParams) -> tuple[list[Any], int]:
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await session.scalars(stmt.offset(page.offset).limit(page.limit))).all()
    return list(rows), int(total or 0)


def apply_patch(obj: M, data: dict[str, Any]) -> M:
    """PATCH: 보낸 필드만 덮어씀."""
    for key, value in data.items():
        setattr(obj, key, value)
    return obj

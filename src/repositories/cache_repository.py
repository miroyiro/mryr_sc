"""api_cache DB 함수 (명주). 외부 API 응답 캐시. TTL 지나면 재조회 (TMDB 최대 180일)."""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ApiCache
from src.repositories.base import paginate
from src.schemas.common import PageParams
from src.utils.time import now_kst

TMDB_MAX_TTL = timedelta(days=180)  # TMDB 약관: 캐시 ≤ 6개월


async def get_fresh(session: AsyncSession, source: str, cache_key: str) -> dict[str, Any] | None:
    """만료 안 된 캐시만 돌려줌. 없거나 만료면 None → 호출자가 외부 API 호출."""
    stmt = select(ApiCache.data).where(
        ApiCache.source == source,
        ApiCache.cache_key == cache_key,
        ApiCache.expires_at > now_kst(),
    )
    return await session.scalar(stmt)


async def get_many_fresh(session: AsyncSession, source: str, keys: list[str]) -> dict[str, dict]:
    """alias 배치 쿼리 전에 '이미 있는 것'을 한 번에 거르기 위함."""
    if not keys:
        return {}
    stmt = select(ApiCache.cache_key, ApiCache.data).where(
        ApiCache.source == source, ApiCache.cache_key.in_(keys), ApiCache.expires_at > now_kst()
    )
    return {k: d for k, d in (await session.execute(stmt)).all()}


async def put(session: AsyncSession, source: str, cache_key: str, data: dict[str, Any], ttl: timedelta) -> None:
    """upsert (UNIQUE(source, cache_key)). 동시에 두 요청이 와도 한 행."""
    if source == "tmdb":
        ttl = min(ttl, TMDB_MAX_TTL)
    now = now_kst()
    stmt = insert(ApiCache).values(source=source, cache_key=cache_key, data=data, cached_at=now, expires_at=now + ttl)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_cache_key",
        set_={"data": stmt.excluded.data, "cached_at": stmt.excluded.cached_at, "expires_at": stmt.excluded.expires_at},
    )
    await session.execute(stmt)


async def get(session: AsyncSession, cache_id: int) -> ApiCache | None:
    return await session.get(ApiCache, cache_id)


async def list_(session: AsyncSession, page: PageParams, *, source: str | None = None,
                expired: bool | None = None) -> tuple[list[ApiCache], int]:
    stmt = select(ApiCache).order_by(ApiCache.cached_at.desc())
    if source:
        stmt = stmt.where(ApiCache.source == source)
    if expired is True:
        stmt = stmt.where(ApiCache.expires_at <= now_kst())
    elif expired is False:
        stmt = stmt.where(ApiCache.expires_at > now_kst())
    return await paginate(session, stmt, page)


async def delete_one(session: AsyncSession, row: ApiCache) -> None:
    await session.delete(row)


async def purge(session: AsyncSession, *, source: str | None = None, expired_only: bool = True,
                before: datetime | None = None) -> int:
    stmt = sa_delete(ApiCache)
    if source:
        stmt = stmt.where(ApiCache.source == source)
    if expired_only:
        stmt = stmt.where(ApiCache.expires_at <= (before or now_kst()))
    result = await session.execute(stmt)
    return result.rowcount or 0


async def delete_by_key(session: AsyncSession, source: str, cache_key: str) -> bool:
    result = await session.execute(
        sa_delete(ApiCache).where(ApiCache.source == source, ApiCache.cache_key == cache_key)
    )
    return (result.rowcount or 0) > 0


async def count_expired(session: AsyncSession) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(ApiCache).where(ApiCache.expires_at <= now_kst())
    ) or 0)

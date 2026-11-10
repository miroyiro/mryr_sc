"""/internal/pipeline/cache — api_cache 조회·삭제·만료 정리 (명주). DELETE 에 body 없음 (06 규칙)."""
from fastapi import APIRouter, Query, Response, status

from src.api.deps import PageDep, SessionDep, meta, not_found
from src.repositories import cache_repository
from src.schemas.cache import CacheDetailOut, CacheOut, PurgeResult
from src.schemas.common import ListResponse

router = APIRouter(prefix="/internal/pipeline/cache", tags=["pipeline:cache"])


@router.get("", response_model=ListResponse[CacheOut])
async def list_cache(session: SessionDep, page: PageDep, source: str | None = Query(None),
                     expired: bool | None = Query(None)):
    items, total = await cache_repository.list_(session, page, source=source, expired=expired)
    return ListResponse(items=items, meta=meta(page, total))


@router.get("/{cacheId}", response_model=CacheDetailOut)
async def get_cache(cacheId: int, session: SessionDep):  # noqa: N803
    row = await cache_repository.get(session, cacheId)
    if row is None:
        raise not_found("cache")
    return row


@router.delete("/{cacheId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cache(cacheId: int, session: SessionDep):  # noqa: N803
    row = await cache_repository.get(session, cacheId)
    if row is None:
        raise not_found("cache")
    await cache_repository.delete_one(session, row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", response_model=PurgeResult)
async def purge_cache(session: SessionDep, source: str | None = Query(None),
                      expired_only: bool = Query(True, alias="expiredOnly")):
    deleted = await cache_repository.purge(session, source=source, expired_only=expired_only)
    await session.commit()
    return PurgeResult(deleted=deleted)

"""/internal/cache — api문서 '리졸빙&캐싱' 기준.

문서 행: GET /health · DELETE /{source}/{key}
문서에 추가한 행: GET (목록) · DELETE (만료분 일괄 정리)
"""
from fastapi import APIRouter, HTTPException, Query, status

from src.api.deps import PageDep, SessionDep, meta
from src.repositories import cache_repository
from src.schemas.cache import CacheDeletedOut, CacheHealthOut, CacheOut, PurgeOut
from src.schemas.common import DataResponse, ListResponse

router = APIRouter(prefix="/internal/cache", tags=["cache"])


@router.get("/health", response_model=DataResponse[CacheHealthOut])
async def cache_health(session: SessionDep):
    try:
        expired = await cache_repository.count_expired(session)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "cache store unavailable") from exc
    # 만료 행이 많이 쌓였으면 정리 배치가 안 돌고 있다는 신호
    return DataResponse(data=CacheHealthOut(status="degraded" if expired > 10_000 else "ok", expired_rows=expired))


@router.delete("/{source}/{key:path}", response_model=DataResponse[CacheDeletedOut])
async def delete_cache(source: str, key: str, session: SessionDep):
    """특정 캐시 강제 만료. key 예: media:154587, tv:209867:ko-KR. 없으면 404."""
    deleted = await cache_repository.delete_by_key(session, source, key)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cache not found")
    await session.commit()
    return DataResponse(data=CacheDeletedOut(deleted=True))


@router.get("", response_model=ListResponse[CacheOut])
async def list_cache(session: SessionDep, page: PageDep, source: str | None = Query(None),
                     expired: bool | None = Query(None)):
    items, total = await cache_repository.list_(session, page, source=source, expired=expired)
    return ListResponse(data=items, meta=meta(page, total))


@router.delete("", response_model=DataResponse[PurgeOut])
async def purge_cache(session: SessionDep, source: str | None = Query(None),
                      expired_only: bool = Query(True, alias="expiredOnly")):
    deleted = await cache_repository.purge(session, source=source, expired_only=expired_only)
    await session.commit()
    return DataResponse(data=PurgeOut(deleted=deleted))

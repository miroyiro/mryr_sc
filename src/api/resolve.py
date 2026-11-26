"""/internal/anilist/* — AniList 리졸빙 & 캐싱 (명주). backend 가 부른다.

문서 행: POST /internal/anilist/sync {season, season_year} → 202 (공통 규칙 'sync 는 202')
문서에 추가한 행:
  POST /internal/anilist/resolve  제목 몇 개 → 후보 (온보딩 '추가 요청' 등, 동기 200)
  POST /internal/anilist/refresh  TTL 지난 anilist_id 재조회 → 202
AniList 가 429/점검이면 503 + Retry-After
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.collectors.api.anilist import AniListRateLimited
from src.schemas.common import DataResponse
from src.schemas.resolve import AnimeRefreshRequest, AnimeResolveRequest, ResolveCandidate
from src.schemas.sync import SeasonSyncRequest
from src.services import anilist_resolver

router = APIRouter(prefix="/internal/anilist", tags=["anilist"])


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync(body: SeasonSyncRequest, bg: BackgroundTasks) -> dict:
    """분기 작품 중 '방영 중·팔로우된 작품'만, TTL 지난 것만 갱신 (bulk seed 금지)."""
    if body.season is None or body.season_year is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "season, season_year 필수")
    bg.add_task(anilist_resolver.sync_season, body.season, body.season_year)
    return {"data": {"season": body.season, "season_year": body.season_year, "status": "queued"}}


@router.post("/resolve", response_model=DataResponse[list[ResolveCandidate]])
async def resolve(body: AnimeResolveRequest):
    try:
        return DataResponse(data=await anilist_resolver.resolve_titles(body.titles))
    except ImportError as exc:  # 준현 anilist 컬렉터 아직 없음
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "anilist collector not ready") from exc
    except AniListRateLimited as exc:  # AniList 429 가 재시도 끝까지 → backend 가 언제 다시 부를지 알게 503 + Retry-After
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "anilist rate limited",
                            headers={"Retry-After": str(exc.retry_after)}) from exc


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh(body: AnimeRefreshRequest, bg: BackgroundTasks) -> dict:
    bg.add_task(anilist_resolver.refresh, body.anilist_ids, force=body.force)
    return {"data": {"count": len(body.anilist_ids), "status": "queued"}}

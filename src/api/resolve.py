"""/internal/anilist/* — AniList 리졸빙 & 재조회 (명주). backend 가 부른다.

resolve: 몇 개 안 되는 제목 → 동기로 후보 반환 (온보딩 '추가 요청' 처리 등)
refresh: TTL 지난 작품 → 202 로 접수만 하고 뒤에서 처리 (화면 응답을 막지 않음)
AniList 가 429/점검이면 503 + Retry-After (06 규칙)
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.schemas.resolve import AnimeRefreshRequest, AnimeResolveRequest, ResolveCandidate
from src.services import anilist_resolver

router = APIRouter(prefix="/internal/anilist", tags=["anilist"])


@router.post("/resolve", response_model=list[ResolveCandidate])
async def resolve(body: AnimeResolveRequest):
    try:
        return await anilist_resolver.resolve_titles(body.titles)
    except ImportError as exc:  # 준현 anilist 컬렉터 아직 없음
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "anilist collector not ready") from exc
    # TODO: 컬렉터가 RateLimited 예외를 정의하면 → 503 + headers={"Retry-After": ...}


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh(body: AnimeRefreshRequest, bg: BackgroundTasks) -> dict:
    bg.add_task(anilist_resolver.refresh, body.anilist_ids, force=body.force)
    return {"status": "queued", "count": len(body.anilist_ids)}

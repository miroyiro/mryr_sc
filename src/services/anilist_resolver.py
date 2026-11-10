"""AniList 리졸빙 & 캐싱 (명주 담당 — 02 역할표).

"외부 API 호출은 전부 scrap 한 곳" 원칙: backend 는 AniList 를 직접 부르지 않는다.
→ rate limit(30req/분)·캐시·ToS 준수를 한 군데서 관리.

1) 제목 → api_cache(anilist, search:<norm>) 확인
2) 없으면 AniList search (준현의 collectors/api/anilist.py) → 후보
3) RapidFuzz 점수 높으면 자동 확정 → backend /internal/catalog/anime upsert
   낮으면 후보만 기록 (관리자 확인)
4) TTL: releasing 1일 / finished 30일 (synced_at 은 backend 가 upsert 시각으로 저장)
- 여러 id 재조회는 GraphQL alias 배치 1번 (refresh)
- 전체 카탈로그 bulk seed 금지 (ToS) → 요청 들어온 것만 (lazy)

준현 컬렉터에 기대하는 인터페이스 (아래 Protocol). 이름이 다르면 여기 어댑터만 고친다.
"""
import logging
from datetime import timedelta
from typing import Any, Protocol

from rapidfuzz import fuzz

from src.clients.backend_client import get_backend
from src.config.database import SessionLocal
from src.config.settings import settings
from src.parsers.name_matcher import AUTO_THRESHOLD, normalize
from src.repositories import cache_repository
from src.schemas.resolve import ResolveCandidate

log = logging.getLogger(__name__)
SOURCE = "anilist"
SEARCH_TTL = timedelta(days=7)


class AniListApi(Protocol):
    async def search_media(self, title: str, *, per_page: int = 5) -> list[dict[str, Any]]: ...
    async def fetch_media_batch(self, anilist_ids: list[int]) -> dict[int, dict[str, Any]]: ...
    async def fetch_season_ids(self, season: str, season_year: int) -> list[dict[str, Any]]:
        """분기 작품의 {id, status} 목록만 (메타데이터 전체 X — bulk seed 금지)."""
        ...


def _get_api() -> AniListApi:
    from src.collectors.api.anilist import AniListCollector  # 준현 파일 (lazy import)
    return AniListCollector()  # type: ignore[return-value]


def media_ttl(media: dict[str, Any]) -> timedelta:
    if (media.get("status") or "").upper() == "RELEASING":
        return timedelta(hours=settings.ANILIST_TTL_RELEASING_HOURS)
    return timedelta(days=settings.ANILIST_TTL_FINISHED_DAYS)


def _score(query: str, media: dict[str, Any]) -> float:
    t = media.get("title") or {}
    names = [t.get("romaji"), t.get("english"), t.get("native"), *(media.get("synonyms") or [])]
    q = normalize(query)
    return max((fuzz.WRatio(q, normalize(n)) / 100 for n in names if n), default=0.0)


def to_anime_payload(media: dict[str, Any]) -> dict[str, Any]:
    """AniList 필드 → 우리 필드명 (04 규칙: coverImage → poster_url). main.anime 컬럼과 같은 키."""
    t = media.get("title") or {}
    return {
        "anilist_id": media["id"],
        "title_romaji": t.get("romaji") or t.get("english") or str(media["id"]),
        "title_native": t.get("native"),
        "title_en": t.get("english"),
        "format": (media.get("format") or "").lower() or None,
        "status": (media.get("status") or "").lower() or None,
        "season": (media.get("season") or "").lower() or None,
        "season_year": media.get("seasonYear"),
        "episodes": media.get("episodes"),
        "genres": media.get("genres"),
        "studios": [s["name"] for s in (media.get("studios") or {}).get("nodes", [])] or None,
        "poster_url": (media.get("coverImage") or {}).get("large"),
        "synopsis_en": media.get("description"),
    }


async def resolve_titles(titles: list[str]) -> list[ResolveCandidate]:
    api = _get_api()
    out: list[ResolveCandidate] = []
    async with SessionLocal() as session:
        for title in titles:
            key = f"search:{normalize(title)}"
            results = await cache_repository.get_fresh(session, SOURCE, key)
            if results is None:
                media_list = await api.search_media(title)
                results = {"media": media_list}
                await cache_repository.put(session, SOURCE, key, results, SEARCH_TTL)
                await session.commit()
            media_list = results.get("media") or []
            best = max(media_list, key=lambda m: _score(title, m), default=None)
            score = _score(title, best) if best else 0.0
            auto = best is not None and score >= AUTO_THRESHOLD
            if auto:
                await get_backend().upsert_anime(to_anime_payload(best))
                await cache_repository.put(session, SOURCE, f"media:{best['id']}", best, media_ttl(best))
                await session.commit()
            out.append(ResolveCandidate(
                title=title,
                anilist_id=best["id"] if best else None,
                matched_title=((best or {}).get("title") or {}).get("romaji"),
                score=round(score, 3),
                auto_confirmed=auto,
            ))
    return out


async def refresh(anilist_ids: list[int], *, force: bool = False) -> int:
    """TTL 지난 것만 alias 배치 1번으로 재조회 → backend upsert. 반환 = 갱신 수."""
    async with SessionLocal() as session:
        keys = [f"media:{i}" for i in anilist_ids]
        fresh = {} if force else await cache_repository.get_many_fresh(session, SOURCE, keys)
        stale = [i for i in anilist_ids if f"media:{i}" not in fresh]
        if not stale:
            return 0
        medias = await _get_api().fetch_media_batch(stale)
        for mid, media in medias.items():
            await get_backend().upsert_anime(to_anime_payload(media))
            await cache_repository.put(session, SOURCE, f"media:{mid}", media, media_ttl(media))
        await session.commit()
        return len(medias)


async def sync_season(season: str, season_year: int) -> int:
    """POST /internal/anilist/sync — api문서: '방영 중·팔로우된 작품'만, TTL 지난 것만.
    1) 분기 작품 id·status 만 조회 → RELEASING 만
    2) (TODO) backend /internal/catalog/names 로 팔로우된 작품 id 를 받아 합집합
    3) refresh() 가 TTL 지난 것만 alias 배치로 재조회 → backend upsert"""
    medias = await _get_api().fetch_season_ids(season.upper(), season_year)
    releasing = [m["id"] for m in medias if (m.get("status") or "").upper() == "RELEASING"]
    return await refresh(releasing)


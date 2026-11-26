"""TMDB 컬렉터 — "어디서 방영(스트리밍)"만. 규약: TmdbCollector(source, client=None) · collect(target, params) · aclose().

받는 것: 작품 id·한국어 제목·원제목·watch/providers(region 의 flatrate) 뿐.
받지 않는 것: overview·poster·season/N·episodes·평점·content_ratings·alternative_titles
  (append_to_response 에 watch/providers 만 → 상세 호출 1회).
※ TMDB 텍스트(제목 포함)는 LLM 입력에 넣지 않는다. 표시·매칭용으로만 쓴다 (약관·출처표시 범위 유지).
캐시는 6개월(180일)을 넘기지 않는다 (cache_expires_at). 출처 표시 문구는 raw_data.attribution.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from rapidfuzz import fuzz

from src.collectors.base_api_collector import ApiError, BaseApiCollector
from src.collectors.scraping.base_scraper import LayoutChanged
from src.collectors.types import CollectedItem, CollectResult
from src.config.settings import settings
from src.models import ScrapeTarget

log = logging.getLogger(__name__)

API_BASE = "https://api.themoviedb.org/3"
PAGE_URL = "https://www.themoviedb.org/tv/{id}"

ANIMATION_GENRE_ID = 16
MATCH_THRESHOLD = 85        # 미만이면 매칭 안 함: 엉뚱한 작품에 OTT 를 붙이는 것보다 안 붙이는 게 낫다
DEFAULT_BATCH_SIZE = 20
DEFAULT_REGION = "KR"
MAX_CACHE_DAYS = 180        # TMDB 약관: 캐시 ≤ 6개월

ATTRIBUTION = ("This product uses the TMDB API but is not endorsed or certified by TMDB. "
               "Streaming availability data provided by JustWatch.")

# TMDB provider_id → 우리 platform 코드.
# 미검증: id 는 공식 목록(/watch/providers/tv?watch_region=KR)과 대조 전. scripts/tmdb_provider_check.py 로 확인할 것.
PROVIDER_PLATFORM: dict[int, str] = {
    8: "netflix",
    1883: "tving",
    97: "watcha",
    356: "wavve",
    337: "disney_plus",
    1881: "coupang_play",
}
# id 가 안 맞을 때 보조: provider_name.casefold() → platform
NAME_PLATFORM: dict[str, str] = {
    "netflix": "netflix",
    "tving": "tving",
    "watcha": "watcha",
    "wavve": "wavve",
    "disney plus": "disney_plus",
    "disney+": "disney_plus",
    "coupang play": "coupang_play",
}


class TmdbCollector(BaseApiCollector):
    source_name = "tmdb"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 무엇: 못 찾은 작품 기록 ({anime_id, title, tmdb_id, reason}).
        # 막는 것: 404·저점수 1건 때문에 잡 전체가 실패하거나, 조용히 사라져 추적 못 하는 것.
        self.misses: list[dict[str, Any]] = []

    # ---------- 인증 ----------
    def _auth_params(self) -> dict[str, str]:
        """무엇: v4 토큰(eyJ…)이면 Authorization 헤더, v3 키면 api_key 쿼리.
        막는 것: 키 없이 요청을 보내 401 로 쿼터만 쓰는 것. 실패 메시지는 base 가 path 만 남겨 키가 안 새어 나감."""
        key = settings.TMDB_API_KEY.get_secret_value() if settings.TMDB_API_KEY else ""
        if not key:
            raise RuntimeError("TMDB_API_KEY not set")
        if key.startswith("eyJ"):
            self.client.headers["Authorization"] = f"Bearer {key}"
            return {}
        return {"api_key": key}

    # ---------- 진입점 ----------
    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        """params={"items":[{anime_id,title,tmdb_id?,season?,year?}], "region":"KR"} 또는 target 1건(anime_id+value)."""
        params = params or {}
        region = params.get("region") or DEFAULT_REGION
        items = list(params.get("items") or [])
        if not items and target is not None:
            items = [{"anime_id": target.anime_id, "title": target.value}]
        batch_size = int(params.get("batch_size") or self.source.cfg("batch_size", DEFAULT_BATCH_SIZE))
        if len(items) > batch_size:
            log.info("tmdb: %d건 중 %d건만 처리 (batch_size)", len(items), batch_size)
            items = items[:batch_size]

        auth = self._auth_params()
        out: list[CollectedItem] = []
        for it in items:
            item = await self.lookup(it, region, auth)
            if item is not None:
                out.append(item)
        return CollectResult(items=out)

    async def lookup(self, it: dict, region: str, auth: dict[str, str]) -> CollectedItem | None:
        """무엇: 작품 1건 → (검색) → 상세 1회 → CollectedItem. season 은 external_id 구분용 입력일 뿐.
        막는 것: 404 는 miss 로 남기고 다음 작품 계속 / 그 외 오류(401·5xx 소진)는 그대로 올려 잡 실패로 기록."""
        tmdb_id, score = it.get("tmdb_id"), None
        try:
            if tmdb_id is None:
                found = await self.search(it.get("title") or "", it.get("year"), auth)
                if found is None:
                    self._miss(it, "no_match")
                    return None
                tmdb_id, score = found
            detail = await self.fetch_detail(tmdb_id, auth)
        except ApiError as exc:
            if exc.status == 404:
                self._miss(it, "not_found", tmdb_id)
                return None
            raise
        return self.build_item(it, detail, region, score)

    def _miss(self, it: dict, reason: str, tmdb_id: Any = None) -> None:
        self.misses.append({"anime_id": it.get("anime_id"), "title": it.get("title"),
                            "tmdb_id": tmdb_id if tmdb_id is not None else it.get("tmdb_id"), "reason": reason})

    # ---------- 호출 ----------
    async def search(self, title: str, year: Any, auth: dict[str, str]) -> tuple[int, float] | None:
        """무엇: /search/tv → 애니(genre 16)만 → 제목·원제목 casefold WRatio 최고점, 85 미만이면 None.
        막는 것: 같은 제목의 실사 드라마·다른 작품에 잘못 붙는 것. results 키가 없으면 LayoutChanged(응답 형식 변경)."""
        query = {"query": title, "language": "ko-KR", "include_adult": "false", **auth}
        if year:
            query["first_air_date_year"] = str(year)
        data = (await self.get(f"{API_BASE}/search/tv", params=query)).json()
        if not isinstance(data, dict) or "results" not in data:
            raise LayoutChanged("tmdb: /search/tv 응답에 results 없음")

        q = title.casefold()
        best: tuple[int, float] | None = None
        for r in data.get("results") or []:
            if ANIMATION_GENRE_ID not in (r.get("genre_ids") or []) or r.get("id") is None:
                continue
            score = max(fuzz.WRatio(q, (r.get(k) or "").casefold()) for k in ("name", "original_name"))
            if best is None or score > best[1]:
                best = (r["id"], score)
        if best is None or best[1] < MATCH_THRESHOLD:
            log.info("tmdb: 미매칭 %r (best=%s)", title, best)
            return None
        return best

    async def fetch_detail(self, tmdb_id: int, auth: dict[str, str]) -> dict:
        """무엇: /tv/{id} 1회, append_to_response 는 watch/providers 만.
        막는 것: 필요 없는 overview·이미지·시즌 데이터를 받아 저장하는 것 / id 없는 응답을 그대로 쓰는 것."""
        query = {"language": "ko-KR", "append_to_response": "watch/providers", **auth}
        data = (await self.get(f"{API_BASE}/tv/{tmdb_id}", params=query)).json()
        if not isinstance(data, dict) or data.get("id") is None:
            raise LayoutChanged(f"tmdb: /tv/{tmdb_id} 응답에 id 없음")
        return data

    # ---------- 변환 ----------
    def build_item(self, it: dict, detail: dict, region: str, score: float | None) -> CollectedItem:
        """무엇: 상세 → raw_item 1건. content·images 는 None, raw_data 에 스트리밍 정보와 출처·캐시 만료만.
        막는 것: TMDB 본문(overview 등) 저장 / 6개월 넘는 캐시."""
        tmdb_id = detail["id"]
        season = it.get("season")
        streaming, others, link = parse_providers(detail, region)
        fetched = datetime.now(timezone.utc)
        cache_days = min(int(self.source.cfg("cache_max_days", MAX_CACHE_DAYS)), MAX_CACHE_DAYS)
        return CollectedItem(
            external_id=f"tv:{tmdb_id}" + (f":s{season}" if season else ""),
            url=PAGE_URL.format(id=tmdb_id),
            title=detail.get("name"),
            content=None,
            images=None,
            raw_data={
                "anime_id": it.get("anime_id"),
                "tmdb_id": tmdb_id,
                "season_number": season,
                "title_ko": detail.get("name"),
                "title_original": detail.get("original_name"),
                "streaming": streaming,
                "other_providers": others,
                "justwatch_link": link,
                "region": region,
                "match_score": score,
                "fetched_at": fetched.isoformat(),
                "cache_expires_at": (fetched + timedelta(days=cache_days)).isoformat(),
                "attribution": ATTRIBUTION,
            },
        )


def parse_providers(detail: dict, region: str) -> tuple[list[str], list[str], str | None]:
    """무엇: watch/providers.results[region].flatrate → (우리 platform 목록, 매핑 안 된 이름, JustWatch 링크).
    막는 것: rent/buy·다른 지역을 '방영 중'으로 잘못 표시 / 키가 빠진 응답에서 KeyError."""
    block = ((detail.get("watch/providers") or {}).get("results") or {}).get(region) or {}
    streaming: list[str] = []
    others: list[str] = []
    for p in block.get("flatrate") or []:
        name = p.get("provider_name") or ""
        platform = PROVIDER_PLATFORM.get(p.get("provider_id")) or NAME_PLATFORM.get(name.casefold())
        if platform:
            if platform not in streaming:
                streaming.append(platform)
        elif name and name not in others:
            others.append(name)
    return streaming, others, block.get("link")

"""X(트위터) 컬렉터. 규약: XCollector(source, client=None) · collect(target, params) · aclose().

- 유료(읽기 건당 과금) → scrape_source.config.monthly_budget_usd 가 없으면 요청 전에 XBudgetNotSet.
  1회 실행 상한은 config.per_run_read_cap (기본 100건).
- since_id 증분(target.last_seen_external_id), 원문은 수정하지 않고 그대로 저장.
- 미디어 URL 저장은 config.store_media 가 true 일 때만 (기본 저장 X).
- target 은 is_verified 인 것만. x_account 는 x_user_id 필수 (handle → id 조회 호출을 하지 않음).
"""
import logging
from datetime import datetime
from typing import Any

from src.collectors.base_api_collector import BaseApiCollector
from src.collectors.scraping.base_scraper import LayoutChanged
from src.collectors.types import CollectedItem, CollectResult
from src.config.settings import settings
from src.models import ScrapeTarget
from src.models.enums import TargetType

log = logging.getLogger(__name__)

API_BASE = "https://api.x.com/2"
COST_PER_READ_USD = 0.005     # 로그용 예상 비용 (건당)

DEFAULT_MAX_RESULTS = 20
DEFAULT_MAX_PAGES = 1
DEFAULT_READ_CAP = 100
TITLE_MAX = 300

COMMON_QUERY = {
    "tweet.fields": "created_at,lang,entities,referenced_tweets,attachments,note_tweet",
    "expansions": "attachments.media_keys,author_id",
    "media.fields": "type,url,preview_image_url",
    "user.fields": "username",
}


class XBudgetNotSet(Exception):
    """monthly_budget_usd 미설정 — 과금 호출을 막는다."""


class XCollector(BaseApiCollector):
    source_name = "x"
    default_delay_ms = 1000

    def _auth(self) -> None:
        """무엇: X_BEARER_TOKEN 을 Authorization 헤더로.
        막는 것: 토큰 없이 요청. 실패 메시지는 base 가 path 만 남기므로 토큰이 안 새어 나감."""
        token = settings.X_BEARER_TOKEN.get_secret_value() if settings.X_BEARER_TOKEN else ""
        if not token:
            raise RuntimeError("X_BEARER_TOKEN not set")
        self.client.headers["Authorization"] = f"Bearer {token}"

    def _request(self, target: ScrapeTarget, max_results: int) -> tuple[str, dict[str, Any], str]:
        """무엇: target 종류별 (url, query, 다음 페이지 파라미터 이름).
        막는 것: x_user_id 없는 계정 수집(→ 다른 사람 계정을 handle 로 잘못 찾는 것) / API 최소 max_results 위반(400)."""
        if target.target_type == TargetType.X_ACCOUNT:
            if not target.x_user_id:
                raise ValueError(f"x_account target {target.value!r}: x_user_id 필수")
            q = {"exclude": "retweets,replies", "max_results": _clamp(max_results, 5)}
            return f"{API_BASE}/users/{target.x_user_id}/tweets", q, "pagination_token"
        if target.target_type == TargetType.KEYWORD:
            q = {"query": f"({target.value}) -is:retweet", "max_results": _clamp(max_results, 10)}
            return f"{API_BASE}/tweets/search/recent", q, "next_token"
        raise ValueError(f"x: 지원하지 않는 target_type {target.target_type!r}")

    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        # 무엇: 예산·대상 검사를 모든 요청보다 먼저.  막는 것: 예산 없이 과금 / 검증 안 된 대상 수집.
        if self.source.cfg("monthly_budget_usd") is None:
            raise XBudgetNotSet("scrape_source.config.monthly_budget_usd 가 없어 X 호출을 막음")
        if target is None:
            raise ValueError("x: target 필요")
        if not target.is_verified:
            raise ValueError(f"x target {target.value!r}: is_verified 아님")

        params = params or {}
        max_results = int(params.get("max_results") or self.source.cfg("max_results", DEFAULT_MAX_RESULTS))
        max_pages = int(params.get("max_pages") or self.source.cfg("max_pages", DEFAULT_MAX_PAGES))
        read_cap = int(self.source.cfg("per_run_read_cap", DEFAULT_READ_CAP))
        url, query, page_param = self._request(target, min(max_results, read_cap))
        query.update(COMMON_QUERY)
        since = target.last_seen_external_id
        if since and since.isdigit():
            query["since_id"] = since
        self._auth()

        items: list[CollectedItem] = []
        newest: str | None = None
        read = 0
        for page in range(max_pages):
            # 막는 것: 다음 페이지까지 읽으면 1회 상한을 넘는 경우 → 요청하지 않고 멈춤
            if page > 0 and read + query["max_results"] > read_cap:
                log.info("x: per_run_read_cap=%d 도달 예정 → 중단", read_cap)
                break
            data = (await self.get(url, params=query)).json()
            if not isinstance(data, dict) or ("data" not in data and "meta" not in data):
                raise LayoutChanged("x: 응답에 data/meta 둘 다 없음")
            meta = data.get("meta") or {}
            newest = newest or meta.get("newest_id")   # 첫 페이지가 가장 최신
            tweets = data.get("data") or []
            read += len(tweets)
            items += [self.build_item(t, data.get("includes") or {}, target) for t in tweets if t.get("id")]
            token = meta.get("next_token")
            if not token:
                break
            query[page_param] = token

        log.info("x: %s 읽음 %d건, 예상 비용 $%.3f", target.value, read, read * COST_PER_READ_USD)
        return CollectResult(items=items, last_seen_external_id=newest or target.last_seen_external_id)

    def build_item(self, tweet: dict, includes: dict, target: ScrapeTarget) -> CollectedItem:
        """무엇: 트윗 1건 → raw_item. content 는 원문 그대로(긴 글은 note_tweet.text).
        막는 것: 원문 가공·축약 저장 / 동의 없는 미디어 저장 / 필드 누락 응답에서 KeyError."""
        tid = str(tweet["id"])
        media_by_key = {m.get("media_key"): m for m in includes.get("media") or []}
        users = {u.get("id"): u.get("username") for u in includes.get("users") or []}
        handle = users.get(tweet.get("author_id")) or (
            target.value if target.target_type == TargetType.X_ACCOUNT else None) or "i"

        content = (tweet.get("note_tweet") or {}).get("text") or tweet.get("text") or ""
        media = [media_by_key[k] for k in (tweet.get("attachments") or {}).get("media_keys") or []
                 if k in media_by_key]
        images = None
        if self.source.cfg("store_media", False):
            images = [m["url"] for m in media if m.get("type") == "photo" and m.get("url")] or None

        return CollectedItem(
            external_id=tid,
            url=f"https://x.com/{handle}/status/{tid}",
            title=content.split("\n", 1)[0][:TITLE_MAX] or None,
            content=content,
            author=handle if handle != "i" else None,
            images=images,
            published_at=_parse_time(tweet.get("created_at")),
            raw_data={
                "tweet_id": tid,
                "author_id": tweet.get("author_id"),
                "lang": tweet.get("lang"),
                "urls": [u["expanded_url"] for u in (tweet.get("entities") or {}).get("urls") or []
                         if u.get("expanded_url")],
                "media_types": [m.get("type") for m in media],
                "referenced": [{"type": r.get("type"), "id": r.get("id")}
                               for r in tweet.get("referenced_tweets") or []],
            },
        )


def _clamp(n: int, lo: int) -> int:
    return max(lo, min(100, n))


def _parse_time(value: str | None) -> datetime | None:
    """'2026-11-20T03:00:00.000Z' → tz-aware UTC. 형식이 다르면 None (한 건 때문에 잡이 죽지 않게)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

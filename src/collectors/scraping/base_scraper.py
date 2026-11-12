"""스크래핑 공통 베이스 (명주). 04 '공통 수집 규칙'을 코드로 강제하는 곳.

- robots.txt 준수 (Disallow 면 요청 안 함) + Crawl-delay 반영
- 자체 User-Agent (다른 봇 위장 금지)
- 소스별 간격: scrape_source.config.delay_ms (애니메이트 10초, 라프텔 1.5초 …)
  → 같은 소스 요청은 프로세스 안에서 '게이트' 하나를 공유 (asyncio.Lock + 마지막 요청 시각)
- 429/5xx 재시도 + Retry-After 존중, 4xx 는 재시도 안 함
- 본문/이미지 저장 금지 소스(store_content=False)는 sanitize 에서 None 처리
- 차단 우회(프록시 회전, UA 바꾸기 등) 하지 않음 → 403 이면 그대로 실패 기록
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import ClassVar
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from src.collectors.types import CollectedItem, CollectResult
from src.config.settings import settings
from src.models import ScrapeSource, ScrapeTarget

log = logging.getLogger(__name__)


class RobotsDisallowed(Exception):
    pass


class LayoutChanged(Exception):
    """응답은 200 인데 기대한 구조(선택자)가 하나도 안 잡힘 → 사이트 개편 의심.
    collect_service 가 받으면 target 을 broken 으로 바꿔서 관리자에게 알림 (조용히 0건 수집 방지)."""


class _SourceGate:
    """같은 소스로 가는 요청 사이 최소 간격 보장. 동시에 여러 코루틴이 불러도 순서대로 통과."""

    def __init__(self, delay_sec: float):
        self.delay_sec = delay_sec
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            gap = self.delay_sec - (time.monotonic() - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last = time.monotonic()


class BaseScraper(ABC):
    # 하위 클래스가 정함
    source_name: ClassVar[str]
    store_content: ClassVar[bool] = False     # 애니플러스·애니메이트·라프텔 = False
    default_delay_ms: ClassVar[int] = 2000

    _gates: ClassVar[dict[str, _SourceGate]] = {}
    _robots: ClassVar[dict[str, RobotFileParser | None]] = {}

    def __init__(self, source: ScrapeSource, client: httpx.AsyncClient | None = None):
        self.source = source
        self.ua = settings.SCRAPER_USER_AGENT
        self._own_client = client is None
        self.client = client or httpx.AsyncClient(
            headers={"User-Agent": self.ua, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=settings.HTTP_TIMEOUT_SEC,
            follow_redirects=True,
        )
        delay_ms = int(source.cfg("delay_ms", self.default_delay_ms))
        self.gate = self._gates.setdefault(source.name, _SourceGate(delay_ms / 1000))

    # ------------------------------------------------------------------ public
    @abstractmethod
    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        """target 하나를 수집해서 CollectedItem 목록으로. DB 저장은 하지 않는다 (collect_service 가 함)."""

    async def aclose(self) -> None:
        if self._own_client:
            await self.client.aclose()

    # ------------------------------------------------------------------ helpers
    async def fetch(self, url: str, *, params: dict | None = None) -> httpx.Response:
        await self._check_robots(url)
        last_exc: Exception | None = None
        for attempt in range(1, settings.HTTP_MAX_RETRIES + 1):
            await self.gate.wait()
            try:
                resp = await self.client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = _retry_after_sec(resp) or 2 ** attempt
                log.warning("%s %s → %s, retry in %ss", self.source_name, url, resp.status_code, wait)
                await asyncio.sleep(wait)
                last_exc = httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
                continue
            resp.raise_for_status()  # 4xx → 바로 예외 (재시도/우회 안 함)
            return resp
        assert last_exc is not None
        raise last_exc

    def sel(self, key: str, default: str) -> str:
        """선택자/패턴을 코드가 아니라 scrape_source.config.selectors 에서 먼저 찾음.
        사이트 HTML 이 바뀌면 배포 없이 PATCH /internal/pipeline/sources/{id} 로 config 만 고치면 됨.
        예: {"selectors": {"row": "ul.board-list li", "title": "a.subject"}}"""
        return (self.source.cfg("selectors") or {}).get(key, default)

    def sanitize(self, item: CollectedItem) -> CollectedItem:
        if not self.store_content:
            item.content = None
            item.images = None   # 다른 사이트 이미지 복사 금지
        return item

    # ------------------------------------------------------------------ robots
    async def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            self._robots[host] = await self._load_robots(host)
        rp = self._robots[host]
        if rp is None:
            return  # robots.txt 없음(404) = 제한 없음
        if not rp.can_fetch(self.ua, url):
            raise RobotsDisallowed(url)
        crawl_delay = rp.crawl_delay(self.ua)
        if crawl_delay and float(crawl_delay) > self.gate.delay_sec:
            self.gate.delay_sec = float(crawl_delay)

    async def _load_robots(self, host: str) -> RobotFileParser | None:
        try:
            resp = await self.client.get(f"{host}/robots.txt")
        except httpx.HTTPError:
            log.warning("robots.txt fetch failed for %s → 보수적으로 진행 안 함", host)
            raise
        if resp.status_code in (404, 410):
            return None  # robots.txt 없음 = 제한 없음
        if resp.status_code >= 400:
            # 401/403/5xx 를 '허용'으로 해석하면 안 됨 (에러 페이지 HTML 을 파싱하면 전부 허용이 됨)
            raise RobotsDisallowed(f"{host}/robots.txt → {resp.status_code}")
        rp = RobotFileParser()
        rp.parse(resp.text.splitlines())
        return rp


def _retry_after_sec(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value and value.isdigit():
        return float(value)
    return None

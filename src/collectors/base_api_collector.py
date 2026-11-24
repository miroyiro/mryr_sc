"""공개 API 컬렉터 공통 베이스 (kopis·anissia). registry 규약 cls(source) · collect() · aclose().

- 같은 소스 요청 간격: scrape_source.config.delay_ms (스크래퍼와 같은 게이트 재사용)
- 429/5xx/연결 오류만 재시도 (Retry-After 존중), 4xx 는 바로 실패
- 실패 메시지에 API 키를 남기지 않음: httpx 예외는 요청 URL(?service=<KEY>)을 품고 있고,
  collect_service 가 repr(exc) + traceback 을 scrape_error 에 저장하므로 → 키 없는 ApiError 로 바꿔 던진다
- robots.txt 는 보지 않음 (웹페이지가 아니라 키 발급받은 공개 API)
"""
import asyncio
import logging
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx

from src.collectors.scraping.base_scraper import _retry_after_sec, _SourceGate
from src.config.settings import settings
from src.models import ScrapeSource

log = logging.getLogger(__name__)

_sleep = asyncio.sleep   # 테스트에서 바꿔 끼워 재시도 대기를 0으로


class ApiError(Exception):
    """키가 빠진 실패 메시지. status = HTTP 상태 (연결 오류면 None)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class BaseApiCollector:
    source_name: ClassVar[str]
    default_delay_ms: ClassVar[int] = 1000
    accept: ClassVar[str] = "application/json"

    _gates: ClassVar[dict[str, _SourceGate]] = {}

    def __init__(self, source: ScrapeSource, client: httpx.AsyncClient | None = None):
        self.source = source
        self._own_client = client is None
        self.client = client or httpx.AsyncClient(
            headers={"User-Agent": settings.SCRAPER_USER_AGENT, "Accept": self.accept},
            timeout=settings.HTTP_TIMEOUT_SEC,
        )
        delay_ms = int(source.cfg("delay_ms", self.default_delay_ms))
        self.gate = self._gates.setdefault(source.name, _SourceGate(delay_ms / 1000))

    async def aclose(self) -> None:
        if self._own_client:
            await self.client.aclose()

    async def get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        where = f"{self.source.name} GET {urlsplit(url).path}"   # 쿼리스트링(키) 제외
        last: ApiError | None = None
        for attempt in range(1, settings.HTTP_MAX_RETRIES + 1):
            await self.gate.wait()
            try:
                resp = await self.client.get(url, params=params)
            except httpx.TransportError as exc:
                last = ApiError(f"{where} → {type(exc).__name__}")
                await _sleep(2 ** attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = ApiError(f"{where} → {resp.status_code}", resp.status_code)
                wait = _retry_after_sec(resp) or 2 ** attempt
                log.warning("%s, retry %s in %ss", last, attempt, wait)
                await _sleep(wait)
                continue
            if resp.status_code >= 400:
                raise ApiError(f"{where} → {resp.status_code}", resp.status_code)
            return resp
        assert last is not None
        raise last

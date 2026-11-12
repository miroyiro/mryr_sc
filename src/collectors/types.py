"""컬렉터 공통 입출력 타입. API(준현) / Feed(준현) / Scraping(명주) 컬렉터가 전부 이 모양으로 돌려준다.
→ collect_service 는 컬렉터 종류를 몰라도 raw_item 에 저장할 수 있음 (다형성)."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from src.models import ScrapeSource, ScrapeTarget


@dataclass(slots=True)
class CollectedItem:
    external_id: str                      # 소스 안에서 유일 (tweet id, 게시글 번호, URL path …)
    url: str
    title: str | None = None
    content: str | None = None            # 본문 저장 금지 소스는 컬렉터가 None 으로
    author: str | None = None
    images: list[str] | None = None
    published_at: datetime | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CollectResult:
    items: list[CollectedItem]
    last_seen_external_id: str | None = None   # 다음 증분 수집 기준 (X since_id, sitemap lastmod …)


class Collector(Protocol):
    source: ScrapeSource

    async def collect(self, target: ScrapeTarget | None, params: dict[str, Any] | None = None) -> CollectResult:
        """params = /internal/{소스}/sync 요청 body (weeks, afterdate, season …). 없으면 기본 동작."""
        ...

    async def aclose(self) -> None: ...

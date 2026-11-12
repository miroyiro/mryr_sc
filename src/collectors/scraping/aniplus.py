"""애니플러스 뉴스 — news sitemap 폴링 (명주). 1~3시간 간격.

- target: target_type='sitemap', value='https://news.aniplustv.com/news-sitemap.xml'
- 저장: 제목·발행일·URL만 (본문 저장 금지). /api/ 호출 금지 → sitemap 만 읽는다.
- 증분: last_seen_external_id = 마지막으로 본 publication_date (ISO 문자열)
- 2026-11-10 확인: 최근 6건 정도만 노출 (<loc>/news/1492</loc>, publication_date +09:00, title 엔티티 디코딩됨)
  → 2시간 간격이면 놓치는 글 없음. robots: /api/ 만 Disallow
- 성격: 사이트맵 = 'feed'에 가깝지만 소스(aniplus) 소유가 명주라 scraping/ 에 둠.
  동시방영(SPA, Playwright)과는 주기·라이브러리·메모리가 달라서 파일을 분리함.
"""
from datetime import datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from src.collectors.scraping.base_scraper import BaseScraper
from src.collectors.types import CollectedItem, CollectResult
from src.models import ScrapeTarget
from src.utils.time import ensure_kst

NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


class AniplusNewsCollector(BaseScraper):
    source_name = "aniplus"
    store_content = False
    default_delay_ms = 3000

    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        if target is None:
            raise ValueError("aniplus news 는 sitemap target 이 필요함")
        resp = await self.fetch(target.value)
        items = parse_news_sitemap(resp.content)

        last_seen = _parse_dt(target.last_seen_external_id) if target.last_seen_external_id else None
        fresh = [i for i in items if i.published_at and (last_seen is None or i.published_at > last_seen)]
        newest = max((i.published_at for i in items if i.published_at), default=None)
        return CollectResult(
            items=[self.sanitize(i) for i in fresh],
            last_seen_external_id=newest.isoformat() if newest else target.last_seen_external_id,
        )


def parse_news_sitemap(xml_bytes: bytes) -> list[CollectedItem]:
    root = ET.fromstring(xml_bytes)
    out: list[CollectedItem] = []
    for url_el in root.findall("sm:url", NS):
        loc = (url_el.findtext("sm:loc", default="", namespaces=NS) or "").strip()
        if not loc:
            continue
        title = url_el.findtext("news:news/news:title", default=None, namespaces=NS)
        pub = url_el.findtext("news:news/news:publication_date", default=None, namespaces=NS)
        out.append(CollectedItem(
            external_id=urlsplit(loc).path.strip("/")[:100] or loc[-100:],
            url=loc,
            title=title.strip()[:300] if title else None,
            published_at=_parse_dt(pub) if pub else None,
            raw_data={"via": "news-sitemap"},
        ))
    return out


def _parse_dt(value: str) -> datetime | None:
    try:
        return ensure_kst(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None

"""라프텔 '라프텔에서 보기' 링크 — 사이트맵 기반 (명주).

왜 사이트맵인가 (2026-11-10 확인)
  - 검색(/search)은 SPA라 HTML 에 /item/ 링크가 없음 → 키워드 검색 방식은 폐기
  - robots.txt 전부 허용. /sitemap.xml(인덱스) → /sitemaps/items.xml 에 작품 4,386개
      <url><loc>https://laftel.net/item/48046</loc><lastmod>2026-11-10</lastmod>…</url>
  - lastmod 는 매일 전부 같은 날짜로 재생성됨 → 증분 기준으로 못 씀
    → laftel_id(숫자, 새 작품일수록 큼)를 커서로 사용: last_seen_external_id = 마지막으로 처리한 id
  - 작품 페이지는 SSR: <meta property="og:title" content="(더빙) 슈가슈가룬 ㅣ 라프텔"/>
    + <link rel="canonical" href="https://laftel.net/item/48046"/>

약관 27조: 복제·배포 금지 → 작품명·URL·laftel_id 만. 줄거리(og:description)·이미지 저장 X.
간격 1.5초(config.delay_ms). 한 번에 최대 config.batch_size(기본 100)편 → 약 2.5분.
처음 한 바퀴(4,386편)는 여러 번 나눠서 돌고, 그 뒤엔 새 작품만.

target: target_type='sitemap', value='https://laftel.net/sitemaps/items.xml'
결과 용도: catalog_service → backend /internal/catalog/streaming (platform=laftel, source=laftel)
⚠️ 로톡 Q3 답변 전까지 scrape_source.enabled = FALSE 유지
"""
import re
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from src.collectors.scraping.base_scraper import BaseScraper, LayoutChanged
from src.collectors.types import CollectedItem, CollectResult
from src.models import ScrapeTarget

SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
ITEM_RE = re.compile(r"/item/(\d+)")
TITLE_SUFFIX_RE = re.compile(r"\s*[ㅣ|│]\s*라프텔\s*$")
VERSION_RE = re.compile(r"^\s*\((더빙|자막|무삭제)\)\s*|\s*\((더빙|자막|무삭제)\)\s*$")


class LaftelSitemapCollector(BaseScraper):
    source_name = "laftel"
    store_content = False
    default_delay_ms = 1500

    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        if target is None:
            raise ValueError("laftel 은 sitemap target 이 필요함")
        resp = await self.fetch(target.value)
        ids = parse_items_sitemap(resp.content)

        cursor = int(target.last_seen_external_id) if (target.last_seen_external_id or "").isdigit() else 0
        batch_size = int((params or {}).get("batch_size") or self.source.cfg("batch_size", 100))
        todo = sorted(i for i in ids if i > cursor)[:batch_size]

        items: list[CollectedItem] = []
        for laftel_id in todo:
            url = f"https://laftel.net/item/{laftel_id}"
            page = await self.fetch(url)
            item = parse_item_page(page.text, laftel_id=laftel_id, url=url)
            if item is not None:
                items.append(self.sanitize(item))
        return CollectResult(
            items=items,
            last_seen_external_id=str(todo[-1]) if todo else target.last_seen_external_id,
        )


def parse_items_sitemap(xml_bytes: bytes) -> list[int]:
    root = ET.fromstring(xml_bytes)
    ids: list[int] = []
    for loc in root.iterfind("sm:url/sm:loc", SM_NS):
        if loc.text and (m := ITEM_RE.search(loc.text)):
            ids.append(int(m[1]))
    if not ids:
        raise LayoutChanged("laftel: items sitemap 에서 /item/{id} 를 하나도 못 찾음")
    return ids


def split_version(title: str) -> tuple[str, str | None]:
    """'(더빙) 슈가슈가룬' → ('슈가슈가룬', 'dub'). 매칭은 앞의 값으로 한다."""
    m = VERSION_RE.search(title)
    if not m:
        return title.strip(), None
    word = m[1] or m[2]
    base = VERSION_RE.sub("", title).strip()
    return base, {"더빙": "dub", "자막": "sub", "무삭제": "uncut"}[word]


def parse_item_page(html: str, *, laftel_id: int, url: str) -> CollectedItem | None:
    soup = BeautifulSoup(html, "lxml")
    og = soup.find("meta", attrs={"property": "og:title"})
    raw_title = (og.get("content") if og else None) or (soup.title.string if soup.title else None)
    if not raw_title:
        return None   # 삭제/비공개 작품 → 건너뜀 (사이트맵 반영 지연)
    title = TITLE_SUFFIX_RE.sub("", raw_title).strip()
    base_title, version = split_version(title)
    canonical = soup.find("link", rel="canonical")
    return CollectedItem(
        external_id=f"item:{laftel_id}",
        url=(canonical.get("href") if canonical else None) or url,
        title=title[:300],
        raw_data={"laftel_id": str(laftel_id), "base_title": base_title, "version": version,
                  "platform": "laftel"},
    )

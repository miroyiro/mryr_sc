"""라프텔 '라프텔에서 보기' 링크 (명주).

- 약관 27조: 복제·배포 금지 → 사실정보(작품명·작품 URL·laftel_id)만. 본문·이미지·줄거리 X
- 1초+ 간격 (config.delay_ms=1500)
- target: target_type='keyword', value = 작품명, anime_id = main.anime.id
- 결과 용도: anime.laftel_id + anime_streaming(platform=laftel, source=laftel, url=딥링크)
  → '카탈로그 보강' 흐름 (processed_item 검수 안 거침)
- ⚠️ 로톡 Q3 답변 전까지 scrape_source.enabled = FALSE 유지

TODO:
  [ ] 검색 결과 페이지 URL 형식과 robots.txt 확인 (내부 API 직접 호출은 하지 않는 것을 기본으로)
  [ ] 작품 페이지 URL 패턴 → laftel_id 추출
"""
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from src.collectors.scraping.base_scraper import BaseScraper
from src.collectors.types import CollectedItem, CollectResult
from src.models import ScrapeTarget

SEARCH_PATH = "/search?keyword={q}"             # TODO: 실제 경로 확인
ITEM_HREF_RE = re.compile(r"/item/(\d+)")       # TODO: 실제 패턴 확인


class LaftelLinkCollector(BaseScraper):
    source_name = "laftel"
    store_content = False
    default_delay_ms = 1500

    async def collect(self, target: ScrapeTarget | None) -> CollectResult:
        if target is None or not target.anime_id:
            raise ValueError("laftel 은 keyword target + anime_id 가 필요함")
        base = self.source.base_url or "https://laftel.net"
        url = urljoin(base, SEARCH_PATH.format(q=quote(target.value)))
        resp = await self.fetch(url)

        soup = BeautifulSoup(resp.text, "lxml")
        items: list[CollectedItem] = []
        for a in soup.find_all("a", href=ITEM_HREF_RE):
            m = ITEM_HREF_RE.search(a["href"])
            if not m:
                continue
            items.append(CollectedItem(
                external_id=f"item:{m[1]}",
                url=urljoin(base, a["href"]),
                title=a.get_text(strip=True)[:300] or None,
                raw_data={"laftel_id": m[1], "query": target.value, "anime_id": target.anime_id},
            ))
        # 후보가 여러 개면 name_matcher 가 제목 유사도로 하나 고름 (process 단계)
        return CollectResult(items=[self.sanitize(i) for i in items])

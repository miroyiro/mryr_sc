"""애니메이트 코리아 페어·이벤트 게시판 (명주).

- 서버 렌더링 HTML: {base_url}/board/list.php?bdId=event
- 10초 간격 (config.delay_ms=10000), 자체 UA
- 저장: 제목·날짜·URL·게시글 번호만. 본문/이미지 저장 금지 (store_content=False)
- target: target_type='board', value = 게시판 목록 URL (예: .../board/list.php?bdId=event)

TODO(구조 확인 — 07 '기술 확인'):
  [ ] 목록 행 CSS 선택자, 게시글 번호 위치, 날짜 형식
  [ ] 상세 페이지에서 '행사 기간·장소'를 가져와도 되는지 (사실정보만) → event_parser 로
"""
import re
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from src.collectors.scraping.base_scraper import BaseScraper
from src.collectors.types import CollectedItem, CollectResult
from src.models import ScrapeTarget
from src.utils.time import ensure_kst

ROW_SELECTOR = "table tbody tr"        # TODO: 실제 구조 확인
TITLE_SELECTOR = "td.subject a"        # TODO
DATE_SELECTOR = "td.date"              # TODO
DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")


class AnimateEventCollector(BaseScraper):
    source_name = "animate"
    store_content = False
    default_delay_ms = 10_000

    async def collect(self, target: ScrapeTarget | None) -> CollectResult:
        if target is None:
            raise ValueError("animate 는 board target 이 필요함")
        resp = await self.fetch(target.value)
        items = self._parse_list(resp.text, base=target.value)

        # 증분: 마지막으로 본 게시글 번호보다 큰 것만
        last_seen = int(target.last_seen_external_id) if (target.last_seen_external_id or "").isdigit() else 0
        new_items = [i for i in items if i.external_id.isdigit() and int(i.external_id) > last_seen]
        newest = max((int(i.external_id) for i in items if i.external_id.isdigit()), default=None)
        return CollectResult(
            items=[self.sanitize(i) for i in new_items],
            last_seen_external_id=str(newest) if newest else target.last_seen_external_id,
        )

    def _parse_list(self, html: str, *, base: str) -> list[CollectedItem]:
        soup = BeautifulSoup(html, "lxml")
        out: list[CollectedItem] = []
        for row in soup.select(ROW_SELECTOR):
            a = row.select_one(TITLE_SELECTOR)
            if not a or not a.get("href"):
                continue
            url = urljoin(base, a["href"])
            post_no = _post_no(url)
            if not post_no:
                continue
            date_el = row.select_one(DATE_SELECTOR)
            published = None
            if date_el and (m := DATE_RE.search(date_el.get_text(strip=True))):
                published = ensure_kst(datetime(int(m[1]), int(m[2]), int(m[3])))
            out.append(CollectedItem(
                external_id=post_no,
                url=url,
                title=a.get_text(strip=True)[:300],
                published_at=published,
                raw_data={"board": "event"},
            ))
        return out


def _post_no(url: str) -> str | None:
    q = parse_qs(urlsplit(url).query)
    for key in ("sno", "no", "idx"):  # TODO: 실제 파라미터 이름 확인
        if q.get(key):
            return q[key][0]
    return None

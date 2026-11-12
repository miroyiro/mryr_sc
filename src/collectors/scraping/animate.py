"""애니메이트 코리아 페어·이벤트 게시판 (명주).

사이트 : https://www.animate-onlineshop.co.kr  (서버 렌더링 HTML, robots: /board/ 허용)
목록   : /board/list.php?bdId=event&period=all   ← 최신순, '예정' 이벤트까지 나옴
상세   : /board/view.php?bdId=event&sno={sno}
간격   : 10초 (config.delay_ms=10000), 자체 UA

목록 한 행(2026-11-10 확인):
  <div class="event_list"><ul><li>
    <div class="board_tit"><em>[페어]</em>
      <a href="javascript:gd_btn_view('event',517 , 'y')"><strong>약사의 혼잣말 animate 페어 …</strong></a></div>
    <div class="board_event_day"><span><strong>이벤트기간</strong> 2026.11.07 00:00 ~ 2026.11.22 23:59</span></div>
  </li>…
상세 본문(.board_zone_view .seem_cont) 텍스트:
  ○개최기간 2026년 11월 7일(토) ~ …   ○개최장소 홍대점/잠실롯데점/부산점/수원점/온라인샵   ○이벤트 내용 …

저장 범위: 제목·라벨·기간·개최장소(사실정보)·URL·게시글 번호. 본문/이미지는 저장 안 함 (store_content=False).
상세는 '새 글'만, 한 번에 최대 config.max_detail(기본 15)개 → 10초 간격이라 최대 2.5분.
"""
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.collectors.scraping.base_scraper import BaseScraper, LayoutChanged
from src.collectors.types import CollectedItem, CollectResult
from src.models import ScrapeTarget
from src.utils.time import ensure_kst

DEFAULT_BASE = "https://www.animate-onlineshop.co.kr"
DETAIL_PATH = "/board/view.php?bdId=event&sno={sno}"

# 선택자 기본값 — 사이트가 바뀌면 scrape_source.config.selectors 로 덮어씀 (배포 없이)
SELECTORS = {
    "row": "div.event_list li",
    "label": ".board_tit em",
    "title": ".board_tit strong",
    "link": ".board_tit a[href]",
    "period": ".board_event_day span",
    "detail_body": ".board_zone_view .seem_cont",
}
SNO_RE = re.compile(r"gd_btn_view\(\s*'event'\s*,\s*(\d+)")
SNO_QS_RE = re.compile(r"[?&]sno=(\d+)")
PERIOD_RE = re.compile(
    r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})\s*~\s*(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})"
)
# '○개최장소' 다음부터 다음 '○' 또는 '※' 전까지
VENUE_RE = re.compile(r"[○◎●■]\s*개최\s*장소\s*[:：]?\s*(.+?)\s*(?=[○◎●■※]|$)", re.S)


class AnimateEventCollector(BaseScraper):
    source_name = "animate"
    store_content = False
    default_delay_ms = 10_000

    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        if target is None:
            raise ValueError("animate 는 board target 이 필요함")
        base = self.source.base_url or DEFAULT_BASE
        resp = await self.fetch(target.value)
        rows = parse_list(resp.text, base=base, sel=self.sel)

        last_seen = int(target.last_seen_external_id) if (target.last_seen_external_id or "").isdigit() else 0
        max_detail = int((params or {}).get("max_detail") or self.source.cfg("max_detail", 15))
        # 오래된 새 글부터 → 상한에 걸려도 다음 실행이 이어서 가져감 (빈틈 없음)
        new_rows = sorted((r for r in rows if int(r.external_id) > last_seen), key=lambda r: int(r.external_id))
        batch = new_rows[:max_detail]

        for item in batch:
            detail = await self.fetch(urljoin(base, DETAIL_PATH.format(sno=item.external_id)))
            item.raw_data.update(parse_detail(detail.text, sel=self.sel))

        newest = max((int(i.external_id) for i in batch), default=None)
        return CollectResult(
            items=[self.sanitize(i) for i in batch],
            last_seen_external_id=str(newest) if newest else target.last_seen_external_id,
        )


def _default_sel(key: str, default: str) -> str:
    return default


def parse_list(html: str, *, base: str = DEFAULT_BASE, sel=_default_sel) -> list[CollectedItem]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select(sel("row", SELECTORS["row"]))
    if not rows:
        raise LayoutChanged(f"animate: 목록 행 0개 (selector={sel('row', SELECTORS['row'])!r})")
    out: list[CollectedItem] = []
    for row in rows:
        link = row.select_one(sel("link", SELECTORS["link"]))
        title_el = row.select_one(sel("title", SELECTORS["title"]))
        if not link or not title_el:
            continue
        href = link["href"]
        m = SNO_RE.search(href) or SNO_QS_RE.search(href)
        if not m:
            continue
        sno = m[1]
        label_el = row.select_one(sel("label", SELECTORS["label"]))
        label = label_el.get_text(strip=True).strip("[] ") if label_el else None
        period_el = row.select_one(sel("period", SELECTORS["period"]))
        period_text = " ".join(period_el.get_text(" ", strip=True).split()) if period_el else None
        start, end = parse_period(period_text or "")
        out.append(CollectedItem(
            external_id=sno,
            url=urljoin(base, DETAIL_PATH.format(sno=sno)),
            title=" ".join(title_el.get_text(" ", strip=True).split())[:300],
            published_at=None,   # 게시판에 작성일 없음 (이벤트 기간만 있음)
            raw_data={
                "board": "event",
                "label": label,               # 페어 / 팝업 / 이벤트 …
                "period_text": period_text,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
        ))
    if not out:
        raise LayoutChanged("animate: 행은 있는데 게시글 번호/제목을 하나도 못 읽음")
    return out


def parse_period(text: str) -> tuple[datetime | None, datetime | None]:
    m = PERIOD_RE.search(text)
    if not m:
        return None, None
    v = [int(x) for x in m.groups()]
    try:
        return (ensure_kst(datetime(v[0], v[1], v[2], v[3], v[4])),
                ensure_kst(datetime(v[5], v[6], v[7], v[8], v[9])))
    except ValueError:
        return None, None


def parse_detail(html: str, *, sel=_default_sel) -> dict:
    """상세에서 '개최장소'만 뽑는다 (사실정보). 본문은 돌려주지 않음."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(sel("detail_body", SELECTORS["detail_body"]))
    if body is None:
        return {"venues": None, "venue_text": None}
    text = " ".join(body.get_text(" ", strip=True).split())
    m = VENUE_RE.search(text)
    if not m:
        return {"venues": None, "venue_text": None}
    venue_text = m[1].strip()[:200]
    venues = [v.strip() for v in re.split(r"[/,·、]", venue_text) if v.strip()]
    return {"venues": venues, "venue_text": venue_text}

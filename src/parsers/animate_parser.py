"""애니메이트 게시판 전용 파서 (명주). raw_item → processed_item(category=fair/popup/…).

컬렉터가 이미 구조화해 둔 raw_data 를 쓴다 → 제목 텍스트에서 날짜를 추측하지 않음.
  raw_data = {label: '페어', start: ISO, end: ISO, venues: ['홍대점', …], venue_text: '홍대점/…'}
라벨이 없거나 모르는 값이면 제목으로 추정(guess_category), 그래도 모르면 'etc'
  (애니메이트 게시판 글 = 전부 오프라인 이벤트라 버리지 않음 → 관리자가 검수)
"""
import re
from datetime import datetime

from src.models import RawItem
from src.models.enums import MainSource, ProcessedCategory
from src.parsers.base_parser import BaseParser, ParsedItem
from src.parsers.event_parser import DateRange, build_event_data, extract_titles, guess_category, parse_date_range

LABEL_MAP: dict[str, ProcessedCategory] = {
    "페어": ProcessedCategory.FAIR,
    "팝업": ProcessedCategory.POPUP,
    "팝업스토어": ProcessedCategory.POPUP,
    "콜라보카페": ProcessedCategory.COLLABO_CAFE,
    "콜라보 카페": ProcessedCategory.COLLABO_CAFE,
    "전시": ProcessedCategory.EXHIBITION,
    "전시회": ProcessedCategory.EXHIBITION,
}
VENUE_PREFIX = "애니메이트 "


def _dates(raw_data: dict, fallback_text: str) -> DateRange | None:
    try:
        start = datetime.fromisoformat(raw_data["start"]) if raw_data.get("start") else None
        end = datetime.fromisoformat(raw_data["end"]) if raw_data.get("end") else None
    except ValueError:
        start = end = None
    if start is None:
        return parse_date_range(fallback_text)
    # '00:00 ~ 23:59' = 하루 종일 행사
    all_day = start.hour == 0 and start.minute == 0 and (end is None or (end.hour, end.minute) == (23, 59))
    return DateRange(start=start, end=end, is_all_day=all_day)


def venue_of(raw_data: dict) -> str | None:
    venues = raw_data.get("venues") or []
    stores = [v for v in venues if "온라인" not in v]
    if not stores:
        return "애니메이트 온라인샵" if venues else None
    return (VENUE_PREFIX + "/".join(stores))[:200]


_NOISE_RE = re.compile(r"\s*(?:in\s+)?animate.*$|\s*(?:페어|팝업|이벤트|기념).*$", re.I)


def title_keywords(title: str) -> list[str]:
    """『』 속 작품명 우선. 없으면 'animate'/'페어' 앞부분 ('약사의 혼잣말 animate 페어 …' → '약사의 혼잣말')."""
    found = extract_titles(title)
    if found:
        return found
    head = _NOISE_RE.sub("", title).strip()
    return [head] if len(head) >= 2 else []


class AnimateEventParser(BaseParser):
    source_names = ("animate",)

    def parse(self, raw: RawItem, *, source_name: str) -> ParsedItem | None:
        if not raw.title:
            return None
        data = raw.raw_data or {}
        label = (data.get("label") or "").strip()
        category = LABEL_MAP.get(label) or guess_category(raw.title) or ProcessedCategory.ETC
        dates = _dates(data, data.get("period_text") or raw.title)
        summary = " · ".join(filter(None, [
            f"[{label}]" if label else None,
            data.get("period_text"),
            f"개최장소: {data['venue_text']}" if data.get("venue_text") else None,
        ])) or None

        event_data = None
        if dates:
            event_data = build_event_data(
                category=category, main_category="anime", title=raw.title,
                source=MainSource.ANIMATE, source_id=raw.external_id, source_url=raw.url, dates=dates,
                venue=venue_of(data),
            )
            event_data["description"] = (f"개최장소: {data['venue_text']}" if data.get("venue_text") else None)
        return ParsedItem(
            category=category,
            title=raw.title,
            summary=summary,
            keywords=title_keywords(raw.title),   # 작품명 후보 → name_matcher
            event_data=event_data,
        )

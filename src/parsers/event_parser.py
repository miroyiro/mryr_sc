"""이벤트 파서 (명주): 제목/본문 텍스트 → event.type + 날짜 + main.event payload.

규칙 기반 (LLM 아님, 02 문서: 매칭·분류는 규칙 + RapidFuzz).
event_data 키 = main.event 컬럼 이름 그대로 (backend 내부 API가 그대로 INSERT).
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from src.models import RawItem
from src.models.enums import MainSource, ProcessedCategory
from src.parsers.base_parser import BaseParser, ParsedItem
from src.utils.time import KST

# 위에서부터 먼저 맞는 것 (구체적인 것 먼저)
TYPE_RULES: list[tuple[ProcessedCategory, re.Pattern]] = [
    (ProcessedCategory.COLLABO_CAFE, re.compile(r"콜라보\s*카페|collabo\s*cafe|카페\s*콜라보", re.I)),
    (ProcessedCategory.POPUP, re.compile(r"팝업|pop[\s\-]?up", re.I)),
    (ProcessedCategory.FAIR, re.compile(r"페어|fair", re.I)),
    (ProcessedCategory.EXHIBITION, re.compile(r"전시|원화전|exhibition", re.I)),
    (ProcessedCategory.CONCERT, re.compile(r"내한|콘서트|공연|live\s*tour|concert", re.I)),
    (ProcessedCategory.RELEASE, re.compile(r"발매|release|앨범|싱글", re.I)),
]

TITLE_BRACKET_RE = re.compile(r"[『《「](.+?)[』》」]")

# "2026.11.20(금) ~ 12.01(일)" / "2026-11-20 ~ 2026-12-01" / "11월 20일 ~ 12월 1일"
_D = r"(?:(?P<{p}y>\d{{4}})[.\-/년]\s*)?(?P<{p}m>\d{{1,2}})[.\-/월]\s*(?P<{p}d>\d{{1,2}})일?"
RANGE_RE = re.compile(_D.format(p="s") + r"[^\d~\-–]*(?:[~\-–]\s*" + _D.format(p="e") + r")?")
TIME_RE = re.compile(r"(?P<h>\d{1,2})\s*[:시]\s*(?P<mi>\d{2})?")


@dataclass(slots=True)
class DateRange:
    start: datetime
    end: datetime | None
    is_all_day: bool


def guess_category(text: str) -> ProcessedCategory | None:
    for category, pattern in TYPE_RULES:
        if pattern.search(text):
            return category
    return None


def extract_titles(text: str) -> list[str]:
    """『』《》「」 속 작품명 (애니플러스 뉴스 ↔ 애니시아 subject 매칭용)."""
    return [t.strip() for t in TITLE_BRACKET_RE.findall(text) if t.strip()]


def parse_date_range(text: str, *, today: date | None = None) -> DateRange | None:
    """연도가 없으면 '오늘 기준 가장 가까운 미래'로 추정. 끝 날짜가 시작보다 앞이면 다음 해로."""
    m = RANGE_RE.search(text)
    if not m:
        return None
    today = today or datetime.now(KST).date()

    def _mk(y: str | None, mo: str, d: str, fallback_year: int) -> date | None:
        try:
            return date(int(y) if y else fallback_year, int(mo), int(d))
        except ValueError:
            return None

    start_d = _mk(m["sy"], m["sm"], m["sd"], today.year)
    if start_d is None:
        return None
    if not m["sy"] and start_d < today - timedelta(days=180):
        start_d = start_d.replace(year=start_d.year + 1)

    end_d = None
    if m["em"]:
        end_d = _mk(m["ey"], m["em"], m["ed"], start_d.year)
        if end_d and end_d < start_d:
            end_d = end_d.replace(year=end_d.year + 1)

    tm = TIME_RE.search(text[m.end():m.end() + 30])
    if tm and 0 <= int(tm["h"]) <= 23:
        start = datetime.combine(start_d, time(int(tm["h"]), int(tm["mi"] or 0)), KST)
        all_day = False
    else:
        start = datetime.combine(start_d, time(0, 0), KST)
        all_day = True
    end = datetime.combine(end_d, time(23, 59), KST) if end_d else None
    return DateRange(start=start, end=end, is_all_day=all_day)


def build_event_data(*, category: ProcessedCategory, main_category: str, title: str,
                     source: MainSource, source_id: str, source_url: str, dates: DateRange,
                     venue: str | None = None, address: str | None = None,
                     artist_id: int | None = None, anime_id: int | None = None) -> dict[str, Any]:
    """main.event INSERT payload. 시간은 ISO 8601 +09:00 (06 규칙)."""
    return {
        "category": main_category,            # 'jpop' | 'anime'
        "type": category.value,               # = event.type
        "title": title[:200],
        "venue": venue,
        "address": address,
        "start_at": dates.start.isoformat(),
        "end_at": dates.end.isoformat() if dates.end else None,
        "is_all_day": dates.is_all_day,
        "source": source.value,
        "source_id": source_id,
        "source_url": source_url,
        "artist_id": artist_id,
        "anime_id": anime_id,
        # lat/lng 은 승인 화면에서 관리자가 보정 (지오코딩은 나중에)
    }


class EventParser(BaseParser):
    """애니메이트 게시판 · X 콜라보카페 글 등 '일정이 있는 글' 공통."""
    source_names = ("animate", "x")

    def __init__(self, main_category: str = "anime"):
        self.main_category = main_category

    def parse(self, raw: RawItem, *, source_name: str) -> ParsedItem | None:
        text = " ".join(filter(None, [raw.title, raw.content]))
        if not text:
            return None
        category = guess_category(text)
        if category is None:
            return None  # 일정 글 아님 → 버림 (X 일반 글 등)
        dates = parse_date_range(text)
        keywords = extract_titles(text)
        title = (raw.title or text)[:200]
        source = MainSource(source_name)
        event_data = None
        if dates:
            event_data = build_event_data(
                category=category, main_category=self.main_category, title=title,
                source=source, source_id=raw.external_id, source_url=raw.url, dates=dates,
            )
        return ParsedItem(
            category=category,
            title=title,
            keywords=keywords,
            event_data=event_data,        # 날짜 못 찾으면 None → 관리자가 채움
            confidence=None,              # name_matcher 가 채움
        )


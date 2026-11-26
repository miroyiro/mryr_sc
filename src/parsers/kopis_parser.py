"""KOPIS 내한 공연 파서: raw_item(컬렉터가 넣은 상세 dict) → processed_item(category=concert).

raw_data 키 = kopis.parse_detail 결과 (title, venue, start_date '2026.12.01', end_date, cast …).
artist_id 는 여기서 정하지 않음 → process_service 의 name_matcher 가 keywords(출연진)로 찾음.
"""
import re
from datetime import datetime, time

from src.models import RawItem
from src.models.enums import MainSource, ProcessedCategory
from src.parsers.base_parser import BaseParser, ParsedItem
from src.parsers.event_parser import DateRange, build_event_data
from src.utils.time import KST

CAST_SPLIT_RE = re.compile(r"\s*[,/]\s*")


def parse_kopis_date(value: str | None):
    try:
        return datetime.strptime(value.strip(), "%Y.%m.%d").date() if value else None
    except ValueError:
        return None


def cast_names(cast: str | None) -> list[str]:
    """'Ado, 요루시카 등' → ['Ado', '요루시카'] (끝의 '등' 제거)."""
    if not cast:
        return []
    names = [re.sub(r"\s*등$", "", n).strip() for n in CAST_SPLIT_RE.split(cast)]
    return [n for n in names if n]


def clean_venue(value: str | None) -> str | None:
    """실제 응답 fcltynm 에 앞 공백·탭이 섞여 옴 (' 네이버 아레나 …\t (아레나)') → 공백 하나로. 원문은 raw_data 에 그대로."""
    if not value:
        return None
    return " ".join(value.split()) or None   # 공백만 있던 값은 None


class KopisParser(BaseParser):
    source_names = ("kopis",)

    def parse(self, raw: RawItem, *, source_name: str) -> ParsedItem | None:
        rd = raw.raw_data or {}
        title = raw.title or rd.get("title")
        if not title:
            return None
        keywords = cast_names(rd.get("cast"))

        event_data = None
        start = parse_kopis_date(rd.get("start_date"))
        if start:   # 날짜를 못 읽으면 event_data=None → 검수 화면에서 관리자가 채움
            end = parse_kopis_date(rd.get("end_date"))
            dates = DateRange(
                start=datetime.combine(start, time(0, 0), KST),
                end=datetime.combine(end, time(23, 59), KST) if end else None,
                is_all_day=True,   # 회차 시간(dtguidance)은 자유 텍스트라 해석하지 않음
            )
            event_data = build_event_data(
                category=ProcessedCategory.CONCERT, main_category="jpop", title=title,
                source=MainSource.KOPIS, source_id=raw.external_id, source_url=raw.url,
                dates=dates, venue=clean_venue(rd.get("venue")),
            )
        return ParsedItem(category=ProcessedCategory.CONCERT, title=title, keywords=keywords, event_data=event_data)

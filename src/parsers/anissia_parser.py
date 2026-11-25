"""애니시아 방영 파서: raw_item(작품 × 방영일 1건) → processed_item(category=broadcast).

raw_data 키 = anissia.parse_item 결과 + broadcast_date('2026-11-30').
broadcast_time 은 정규 요일(0~6)일 때만 'HH:MM', 아니면 None → 종일 일정.
anime_id 는 여기서 정하지 않음 → process_service 의 name_matcher 가 keywords(한국어·원제)로 찾음.
"""
from datetime import date, datetime, time

from src.models import RawItem
from src.models.enums import MainSource, ProcessedCategory
from src.parsers.base_parser import BaseParser, ParsedItem
from src.parsers.event_parser import DateRange, build_event_data
from src.utils.time import KST


def _time(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:   # '25:00' 같은 심야 표기 → 종일로
        return None


class AnissiaParser(BaseParser):
    source_names = ("anissia",)

    def parse(self, raw: RawItem, *, source_name: str) -> ParsedItem | None:
        rd = raw.raw_data or {}
        title = raw.title or rd.get("title_ko")
        if not title or not rd.get("broadcast_date"):
            return None
        keywords = [t for t in (rd.get("title_ko"), rd.get("original_title")) if t]

        day = date.fromisoformat(rd["broadcast_date"])
        at = _time(rd.get("broadcast_time"))
        dates = DateRange(start=datetime.combine(day, at or time(0, 0), KST), end=None, is_all_day=at is None)
        event_data = build_event_data(
            category=ProcessedCategory.BROADCAST, main_category="anime", title=title,
            source=MainSource.ANISSIA, source_id=raw.external_id, source_url=raw.url, dates=dates,
        )
        return ParsedItem(category=ProcessedCategory.BROADCAST, title=title, keywords=keywords, event_data=event_data)

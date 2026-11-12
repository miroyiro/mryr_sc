"""뉴스 파서: 애니플러스 뉴스 · UMJ RSS → processed_item(category=news).
담당 미정 (03) — 지금은 제목만 쓰는 최소 버전. 본문 저장 금지 소스라 content 는 안 봄."""
from src.models import RawItem
from src.models.enums import ProcessedCategory
from src.parsers.base_parser import BaseParser, ParsedItem
from src.parsers.event_parser import extract_titles


class NewsParser(BaseParser):
    source_names = ("aniplus", "umj")

    def parse(self, raw: RawItem, *, source_name: str) -> ParsedItem | None:
        if not raw.title:
            return None
        return ParsedItem(category=ProcessedCategory.NEWS, title=raw.title, keywords=extract_titles(raw.title))

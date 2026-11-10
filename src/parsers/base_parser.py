"""파서 공통 (raw_item → processed_item 값). 파서는 DB를 모른다 → 단위 테스트가 쉬움."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.models import RawItem
from src.models.enums import ProcessedCategory


@dataclass(slots=True)
class ParsedItem:
    category: ProcessedCategory
    title: str
    summary: str | None = None
    keywords: list[str] = field(default_factory=list)
    event_data: dict[str, Any] | None = None   # category != news 일 때 main.event payload
    artist_id: int | None = None
    anime_id: int | None = None
    confidence: Decimal | None = None

    def to_values(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "title": self.title[:200],
            "summary": (self.summary or None) and self.summary[:500],
            "keywords": self.keywords or None,
            "event_data": self.event_data,
            "artist_id": self.artist_id,
            "anime_id": self.anime_id,
            "confidence": self.confidence,
        }


class BaseParser(ABC):
    source_names: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, raw: RawItem, *, source_name: str) -> ParsedItem | None:
        """None = 서비스와 무관한 글 (저장 안 함). source_name = scrape_source.name"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from src.models.enums import ProcessedCategory, ProcessedStatus
from src.schemas.common import ORMModel


class ProcessedItemOut(ORMModel):
    id: int
    raw_item_id: int
    artist_id: int | None
    anime_id: int | None
    category: ProcessedCategory
    title: str
    summary: str | None
    keywords: list[str] | None
    event_data: dict[str, Any] | None
    status: ProcessedStatus
    confidence: Decimal | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    reject_reason: str | None
    published_event_id: int | None
    published_news_id: int | None
    created_at: datetime


class ProcessedItemUpdate(BaseModel):
    """검수자가 승인 전에 고치는 값 (매칭 대상, 카테고리, 이벤트 정보)."""
    artist_id: int | None = None
    anime_id: int | None = None
    category: ProcessedCategory | None = None
    title: str | None = Field(None, max_length=200)
    summary: str | None = Field(None, max_length=500)
    event_data: dict[str, Any] | None = None


class ApproveRequest(BaseModel):
    reviewed_by: int  # main.users.id (admin)


class RejectRequest(BaseModel):
    reviewed_by: int
    reject_reason: str = Field(max_length=255)


class PublishResult(BaseModel):
    id: int
    status: ProcessedStatus
    published_event_id: int | None
    published_news_id: int | None

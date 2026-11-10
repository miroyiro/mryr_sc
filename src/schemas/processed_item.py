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
    updated_at: datetime


class ReviewItemOut(BaseModel):
    """GET /internal/pipeline/review 목록 한 줄. 원본과 비교하라고 source_url 포함.
    api문서 예시의 artist{id,name} 중 name 은 main DB 에 있어서 scrap 은 id 만 줌 (이름은 backend 가 붙임)."""
    id: int
    artist_id: int | None
    anime_id: int | None
    title: str
    category: ProcessedCategory
    status: ProcessedStatus
    confidence: Decimal | None
    source_url: str
    created_at: datetime


class ProcessedItemUpdate(BaseModel):
    """PATCH /internal/pipeline/processedItems/{id} — 승인 전 보정."""
    title: str | None = Field(None, max_length=200)
    summary: str | None = Field(None, max_length=500)
    category: ProcessedCategory | None = None
    # api문서에 없던 필드 (추가 반영): 매칭 대상·이벤트 정보 보정
    artist_id: int | None = None
    anime_id: int | None = None
    event_data: dict[str, Any] | None = None


class ApproveRequest(BaseModel):
    reviewer_id: int  # main.users.id (admin) — backend 가 관리자 토큰 확인 후 넣어서 호출


class RejectRequest(BaseModel):
    reviewer_id: int
    reason: str = Field(max_length=255)


class ApproveOut(BaseModel):
    id: int
    status: ProcessedStatus
    published_event_id: int | None
    published_news_id: int | None
    reviewed_at: datetime | None


class RejectOut(BaseModel):
    id: int
    status: ProcessedStatus
    reason: str | None


class CandidateOut(BaseModel):
    """GET /internal/events/candidates — 팝업 후보 큐 (= processed_item 중 popup·collabo_cafe·fair)."""
    candidate_id: int
    category: ProcessedCategory
    source: str
    account: str | None
    url: str
    keywords: list[str] | None
    published_at: datetime | None
    status: ProcessedStatus

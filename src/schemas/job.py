from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import ScrapeJobStatus
from src.schemas.common import ORMModel


class JobOut(ORMModel):
    id: int
    source_id: int
    target_id: int | None
    schedule_id: int | None
    retry_of: int | None
    target: str | None
    status: ScrapeJobStatus
    total_count: int
    collected_count: int
    duplicate_count: int
    error_count: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class JobCreate(BaseModel):
    """POST /internal/pipeline/jobs — 수동 실행 (schedule_id = NULL).
    target_id 없으면 소스 전체. target 은 표시용 문자열(예: '@Aimer_and_staff')."""
    source_id: int
    target_id: int | None = None
    target: str | None = Field(None, max_length=500)


class StatsToday(BaseModel):
    scraped: int
    new: int
    duplicate: int
    processed: int
    failed: int


class StatsOut(BaseModel):
    today: StatsToday

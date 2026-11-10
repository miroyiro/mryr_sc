from datetime import datetime

from pydantic import BaseModel

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
    """수동 실행 (schedule_id = NULL)."""
    source_id: int
    target_id: int | None = None

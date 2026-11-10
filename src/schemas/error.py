from datetime import datetime

from pydantic import BaseModel

from src.models.enums import ErrorJobType, ErrorStatus
from src.schemas.common import ORMModel


class ErrorOut(ORMModel):
    id: int
    job_type: ErrorJobType
    job_id: int
    raw_item_id: int | None
    type: str
    message: str
    stack: str | None
    status: ErrorStatus
    retry_count: int
    resolved_at: datetime | None
    created_at: datetime


class ErrorUpdate(BaseModel):
    status: ErrorStatus  # resolved / ignored

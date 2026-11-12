from datetime import datetime
from typing import Any

from pydantic import Field

from src.schemas.common import ORMModel


class RawItemOut(ORMModel):
    """api문서 GET /internal/pipeline/rawItems — 응답 필드는 job_id (DB 컬럼은 scrape_job_id)."""
    id: int
    source_id: int
    job_id: int = Field(validation_alias="scrape_job_id")
    external_id: str
    title: str | None
    content: str | None
    author: str | None
    url: str
    published_at: datetime | None
    collected_at: datetime
    raw_data: dict[str, Any] | None = None
    # images 는 응답에서 뺀다 (화면 노출 금지 규칙)

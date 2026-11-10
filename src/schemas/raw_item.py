from datetime import datetime
from typing import Any

from src.schemas.common import ORMModel


class RawItemOut(ORMModel):
    id: int
    source_id: int
    scrape_job_id: int
    external_id: str
    url: str
    title: str | None
    content: str | None
    author: str | None
    published_at: datetime | None
    collected_at: datetime
    raw_data: dict[str, Any] | None
    # images 는 응답에서 뺀다 (화면 노출 금지 규칙)

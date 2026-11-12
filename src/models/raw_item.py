from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin


class RawItem(IdMixin, Base):
    __tablename__ = "raw_item"

    source_id: Mapped[int] = mapped_column(ForeignKey("scrape_source.id", ondelete="CASCADE"))
    scrape_job_id: Mapped[int] = mapped_column(ForeignKey("scrape_job.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str | None] = mapped_column(Text)              # 본문 저장 금지 소스는 NULL
    author: Mapped[str | None] = mapped_column(String(100))
    images: Mapped[list[str] | None] = mapped_column(JSONB)        # 화면 노출 금지
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hash: Mapped[str] = mapped_column(CHAR(64))

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, CreatedAtMixin, IdMixin


class ScrapeError(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "scrape_error"

    job_type: Mapped[str] = mapped_column(String(10))       # ErrorJobType
    job_id: Mapped[int] = mapped_column(BigInteger)          # 다형 참조 (scrape_job / process_job)
    raw_item_id: Mapped[int | None] = mapped_column(ForeignKey("raw_item.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(50))            # parse_error, http_429, timeout, robots_disallow …
    message: Mapped[str] = mapped_column(String(1000))
    stack: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="unresolved")  # ErrorStatus
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

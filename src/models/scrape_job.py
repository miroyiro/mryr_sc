from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, CreatedAtMixin, IdMixin


class ScrapeJob(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "scrape_job"

    source_id: Mapped[int] = mapped_column(ForeignKey("scrape_source.id", ondelete="CASCADE"))
    target_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_target.id", ondelete="SET NULL"))
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_schedule.id", ondelete="SET NULL"))
    retry_of: Mapped[int | None] = mapped_column(ForeignKey("scrape_job.id", ondelete="SET NULL"))
    target: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="queued")  # ScrapeJobStatus
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    collected_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

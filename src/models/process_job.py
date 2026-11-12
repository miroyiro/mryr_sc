from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, CreatedAtMixin, IdMixin


class ProcessJob(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "process_job"

    scrape_job_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_job.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="queued")  # ProcessJobStatus
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TimestampMixin


class ScrapeSchedule(IdMixin, TimestampMixin, Base):
    __tablename__ = "scrape_schedule"

    source_id: Mapped[int] = mapped_column(ForeignKey("scrape_source.id", ondelete="CASCADE"))
    target_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_target.id", ondelete="CASCADE"))
    schedule_type: Mapped[str] = mapped_column(String(10), default="interval")  # ScheduleType
    interval_minutes: Mapped[int | None] = mapped_column(Integer)
    cron_expression: Mapped[str | None] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

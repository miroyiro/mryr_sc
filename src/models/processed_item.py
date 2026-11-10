from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TimestampMixin


class ProcessedItem(IdMixin, TimestampMixin, Base):
    """검수 대기열 + 팝업 후보 큐 겸용. raw_item 1건 = processed_item 1건 (uq_processed_raw)."""
    __tablename__ = "processed_item"

    raw_item_id: Mapped[int] = mapped_column(ForeignKey("raw_item.id", ondelete="CASCADE"), unique=True)
    process_job_id: Mapped[int | None] = mapped_column(ForeignKey("process_job.id", ondelete="SET NULL"))
    artist_id: Mapped[int | None] = mapped_column(BigInteger)
    anime_id: Mapped[int | None] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(20))                # ProcessedCategory
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(String(500))
    keywords: Mapped[list[str] | None] = mapped_column(JSONB)
    event_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # main.event payload
    status: Mapped[str] = mapped_column(String(10), default="pending")  # ProcessedStatus
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)      # main.users.id (admin)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    published_event_id: Mapped[int | None] = mapped_column(BigInteger)
    published_news_id: Mapped[int | None] = mapped_column(BigInteger)

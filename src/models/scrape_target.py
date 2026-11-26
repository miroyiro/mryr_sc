from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TimestampMixin


class ScrapeTarget(IdMixin, TimestampMixin, Base):
    __tablename__ = "scrape_target"

    source_id: Mapped[int] = mapped_column(ForeignKey("scrape_source.id", ondelete="CASCADE"))
    target_type: Mapped[str] = mapped_column(String(20))           # TargetType
    artist_id: Mapped[int | None] = mapped_column(BigInteger)      # main.artist.id (FK 없음)
    anime_id: Mapped[int | None] = mapped_column(BigInteger)       # main.anime.id  (FK 없음)
    value: Mapped[str] = mapped_column(String(500))
    x_user_id: Mapped[str | None] = mapped_column(String(30))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="active")
    crawl_interval_sec: Mapped[int] = mapped_column(Integer, default=3600)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_external_id: Mapped[str | None] = mapped_column(String(100))
    # 0005 (관리 GUI). verified_by = admin_user.id (main.users 아님)
    admin_note: Mapped[str | None] = mapped_column(String(500))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("admin_user.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

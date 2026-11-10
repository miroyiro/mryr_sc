from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin


class ApiCache(IdMixin, Base):
    __tablename__ = "api_cache"

    source: Mapped[str] = mapped_column(String(30))         # anilist, tmdb, anissia, kopis, wikidata
    cache_key: Mapped[str] = mapped_column(String(255))     # media:154587, tv:209867:ko-KR
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # TMDB ≤ 180일

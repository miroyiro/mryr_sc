from typing import Any

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TimestampMixin


class ScrapeSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "scrape_source"

    name: Mapped[str] = mapped_column(String(50), unique=True)
    type: Mapped[str] = mapped_column(String(10))                 # SourceType
    base_url: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    def cfg(self, key: str, default: Any = None) -> Any:
        return (self.config or {}).get(key, default)

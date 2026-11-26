from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, CreatedAtMixin, IdMixin


class AdminSession(IdMixin, CreatedAtMixin, Base):
    """로그인 세션 (0005). 쿠키 원문 X, sha256(쿠키) 만 저장. 로그아웃 = 행 삭제."""
    __tablename__ = "admin_session"

    admin_user_id: Mapped[int] = mapped_column(ForeignKey("admin_user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, IdMixin, TimestampMixin


class AdminUser(IdMixin, TimestampMixin, Base):
    """관리 GUI 계정 (0005). 비밀번호 원문은 어디에도 저장하지 않음 → password_hash 만."""
    __tablename__ = "admin_user"

    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))   # src/admin/security.py 형식
    role: Mapped[str] = mapped_column(String(10))             # editor | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

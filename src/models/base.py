"""모델 공통 mixin. Base 는 config/database.py 의 것을 그대로 씀 (migrations/env.py 와 같은 metadata).

테이블은 Alembic(SQL)이 만들고, 모델은 '설계도'로만 쓴다.
→ 모델에 CHECK/인덱스를 다시 적지 않는다 (진실의 원천 = 마이그레이션).
→ 그래서 `alembic revision --autogenerate` 는 쓰지 않는다 (모델에 없는 인덱스를 지우려 함). revision 은 손으로.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, func
from sqlalchemy.orm import Mapped, mapped_column

from src.config.database import Base

__all__ = ["Base", "IdMixin", "CreatedAtMixin", "TimestampMixin"]


class IdMixin:
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    # DB 트리거(set_updated_at)가 갱신. server_onupdate는 "DB가 바꾼다"는 표시만.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now(), nullable=False
    )

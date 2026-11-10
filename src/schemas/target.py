from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import TargetStatus, TargetType
from src.schemas.common import ORMModel


class TargetOut(ORMModel):
    id: int
    source_id: int
    target_type: TargetType
    artist_id: int | None
    anime_id: int | None
    value: str
    x_user_id: str | None
    is_verified: bool
    status: TargetStatus
    crawl_interval_sec: int
    last_crawled_at: datetime | None
    last_seen_external_id: str | None
    created_at: datetime
    updated_at: datetime


class TargetCreate(BaseModel):
    source_id: int
    target_type: TargetType
    value: str = Field(max_length=500)
    artist_id: int | None = None
    anime_id: int | None = None
    x_user_id: str | None = None
    crawl_interval_sec: int = Field(3600, ge=60)
    # is_verified 는 생성 시 항상 FALSE → /verify 로만 켬 (관리자 검증 흐름 강제)


class TargetUpdate(BaseModel):
    value: str | None = Field(None, max_length=500)
    artist_id: int | None = None
    anime_id: int | None = None
    x_user_id: str | None = None
    status: TargetStatus | None = None
    crawl_interval_sec: int | None = Field(None, ge=60)


class TargetVerify(BaseModel):
    is_verified: bool = True
    reviewed_by: int  # main.users.id (admin) — backend가 토큰에서 꺼내 넣어줌

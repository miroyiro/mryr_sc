from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.schemas.common import ORMModel


class CacheHealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    store: Literal["postgres", "redis"] = "postgres"   # MVP = scrap DB 의 api_cache 테이블
    expired_rows: int


class CacheDeletedOut(BaseModel):
    deleted: bool


class CacheOut(ORMModel):
    id: int
    source: str
    cache_key: str
    cached_at: datetime
    expires_at: datetime


class PurgeOut(BaseModel):
    deleted: int

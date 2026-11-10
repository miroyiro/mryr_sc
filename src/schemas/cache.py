from datetime import datetime

from pydantic import BaseModel

from src.schemas.common import ORMModel


class CacheOut(ORMModel):
    id: int
    source: str
    cache_key: str
    cached_at: datetime
    expires_at: datetime
    # data 는 크니까 목록에선 뺀다. 상세 조회에서만.


class CacheDetailOut(CacheOut):
    data: dict


class PurgeResult(BaseModel):
    deleted: int

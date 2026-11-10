"""공통 응답 형태 (06 규칙): 목록 = items + meta, 빈 목록 = 200 + [].
body/response 필드는 snake_case, query는 camelCase(alias)."""
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageMeta(BaseModel):
    page: int
    limit: int
    total: int


class ListResponse(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMeta


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


class QueuedResponse(BaseModel):
    """202 응답 (큐 접수, 나중에 처리)."""
    job_id: int
    status: str = "queued"

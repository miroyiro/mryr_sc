"""공통 응답 형태 — api문서 '공통 규칙'
- 성공 응답은 { "data": ..., "meta"?: {...} } 로 감싼다. 목록이면 meta 에 page·limit·total
- 빈 목록은 404 가 아니라 200 + 빈 배열
- body/response 필드는 snake_case, query·경로 변수는 camelCase
"""
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PageMeta(BaseModel):
    page: int
    limit: int
    total: int


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class DataResponse(BaseModel, Generic[T]):
    data: T


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    limit: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


class QueuedOut(BaseModel):
    """202 (큐 접수, 나중에 처리) 응답의 data."""
    job_ids: list[int]
    status: str = "queued"


class DeletedOut(BaseModel):
    id: int
    deleted: bool = True

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.models.enums import SourceType
from src.schemas.common import ORMModel


class SourceOut(ORMModel):
    id: int
    name: str
    type: SourceType
    base_url: str | None
    enabled: bool
    auto_publish: bool
    description: str | None
    config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SourceCreate(BaseModel):
    name: str
    type: SourceType
    base_url: str | None = None
    enabled: bool = False
    auto_publish: bool = False
    description: str | None = None
    config: dict[str, Any] | None = None


class SourceUpdate(BaseModel):
    """PATCH = 일부 수정. 보낸 필드만 바꾼다 (model_dump(exclude_unset=True))."""
    base_url: str | None = None
    enabled: bool | None = None
    auto_publish: bool | None = None
    description: str | None = None
    config: dict[str, Any] | None = None

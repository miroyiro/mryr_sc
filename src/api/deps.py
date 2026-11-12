"""라우터 공통 의존성: DB 세션, 내부 키 검사, 페이지 파라미터(camelCase query)."""
import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.config.settings import settings
from src.schemas.common import PageMeta, PageParams

SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def require_internal_key(x_internal_key: Annotated[str | None, Header()] = None) -> None:
    """/internal/* 전부. 기본 거부 (Zero Trust): 키 없거나 다르면 401.
    compare_digest = 비교 시간이 일정 → 타이밍 공격으로 키를 한 글자씩 알아내는 것 방지."""
    expected = settings.INTERNAL_KEY.get_secret_value()
    if not x_internal_key or not hmac.compare_digest(x_internal_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal key")


def page_params(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)) -> PageParams:
    return PageParams(page=page, limit=limit)


PageDep = Annotated[PageParams, Depends(page_params)]


def meta(page: PageParams, total: int) -> PageMeta:
    return PageMeta(page=page.page, limit=page.limit, total=total)


def not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)

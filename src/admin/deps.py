"""/admin/api/* 권한 의존성. 읽기·쓰기 검사는 전부 여기서 → 라우터에서 빠뜨릴 수 없게 한 곳에 모음.

- require_reader : 로그인 사용자, 또는 PUBLIC_READ=true 일 때 비로그인 GET 만. 그 외 401
- require_editor / require_admin : 세션(401) → CSRF 헤더(403) → 역할(403) 순서. PUBLIC_READ 와 무관
"""
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from src.admin.security import token_hash
from src.admin.store import AdminStore
from src.api.deps import SessionDep
from src.config.settings import settings

SESSION_COOKIE = "mryr_admin"
ROLE_RANK = {"editor": 1, "admin": 2}   # admin 은 editor 권한을 포함


@dataclass(frozen=True)
class Principal:
    """로그인한 사람. 비밀번호 해시 등은 담지 않음 (라우터로 새어 나가지 않게)."""
    user_id: int
    username: str
    role: str
    csrf_token: str


def utcnow() -> datetime:
    return datetime.now(UTC)


def get_store(db: SessionDep) -> AdminStore:
    return AdminStore(db)


StoreDep = Annotated[AdminStore, Depends(get_store)]


async def current_principal(
    store: StoreDep, token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Principal | None:
    """쿠키 → sha256 → DB 세션 조회. 없거나 만료·로그아웃·비활성 계정이면 None (=비로그인)."""
    if not token:
        return None
    found = await store.get_session_user(token_hash(token), utcnow())
    if found is None:
        return None
    sess, user = found
    return Principal(user_id=user.id, username=user.username, role=user.role, csrf_token=sess.csrf_token)


PrincipalDep = Annotated[Principal | None, Depends(current_principal)]


async def require_reader(request: Request, principal: PrincipalDep) -> Principal | None:
    """반환값 None = 비로그인 공개 읽기 → 라우터는 반드시 Public* 화이트리스트 스키마로 응답해야 함."""
    if principal is not None:
        return principal
    if settings.PUBLIC_READ and request.method == "GET":
        return None
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")


def require_role(min_role: str):
    async def dep(
        principal: PrincipalDep,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if principal is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
        # 다른 사이트가 쿠키를 실어 보내도 CSRF 토큰은 모름 → 헤더 값이 세션 값과 같아야 통과
        if not x_csrf_token or not hmac.compare_digest(x_csrf_token, principal.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf token invalid")
        if ROLE_RANK.get(principal.role, 0) < ROLE_RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return principal
    return dep


ReaderDep = Annotated[Principal | None, Depends(require_reader)]
EditorDep = Annotated[Principal, Depends(require_role("editor"))]
AdminDep = Annotated[Principal, Depends(require_role("admin"))]

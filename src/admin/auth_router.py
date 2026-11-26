"""/admin/api/login · logout · me — 관리 GUI 로그인. 회원가입 없음 (계정은 scripts/create_admin.py)."""
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel, Field

from src.admin.deps import SESSION_COOKIE, EditorDep, PrincipalDep, StoreDep, utcnow
from src.admin.security import DUMMY_HASH, login_limiter, new_token, token_hash, verify_password
from src.config.settings import settings

router = APIRouter(prefix="/admin/api", tags=["admin:auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=256)


class MeOut(BaseModel):
    authenticated: bool
    public_read: bool
    username: str | None = None
    role: str | None = None
    csrf_token: str | None = None   # JS 가 쓰기 요청 헤더(X-CSRF-Token)에 넣음. 쿠키는 HttpOnly 라 JS 가 못 읽음


def _set_session_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        SESSION_COOKIE, token,
        max_age=settings.SESSION_TTL_HOURS * 3600,
        path="/admin",              # /internal·/health 요청엔 쿠키가 안 붙음
        httponly=True,              # JS(XSS) 로 쿠키를 못 읽음
        samesite="lax",             # 다른 사이트에서 보낸 POST 에는 쿠키가 안 붙음
        secure=settings.COOKIE_SECURE,   # Funnel(HTTPS) 운영에서 true
    )


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, response: Response, store: StoreDep):
    username = body.username.strip()
    if login_limiter.is_locked(username):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many failed attempts, try later")

    user = await store.get_user_by_username(username)
    # 사용자가 없어도 해시 검증 1회 → 응답 시간이 같아서 계정 존재 여부가 안 드러남
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not (user and ok and user.is_active):
        login_limiter.fail(username)
        # 어떤 이유로 실패했는지 알려주지 않음 (없는 계정·틀린 비번·비활성 구분 X)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")

    login_limiter.success(username)
    token, csrf = new_token(), new_token()
    now = utcnow()
    await store.create_session(user.id, token_hash(token), csrf,
                               expires_at=now + timedelta(hours=settings.SESSION_TTL_HOURS), now=now)
    _set_session_cookie(response, token)
    return MeOut(authenticated=True, public_read=settings.PUBLIC_READ,
                 username=user.username, role=user.role, csrf_token=csrf)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    _: EditorDep, store: StoreDep, response: Response,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    """세션 행 삭제 → 같은 쿠키를 다시 보내도 즉시 무효. CSRF 필수 (남이 강제로 로그아웃 못 시키게)."""
    if token:
        await store.delete_session(token_hash(token))
    response.delete_cookie(SESSION_COOKIE, path="/admin", httponly=True, samesite="lax",
                           secure=settings.COOKIE_SECURE)


@router.get("/me", response_model=MeOut)
async def me(principal: PrincipalDep):
    """화면이 처음 뜰 때 호출: 로그인 여부·공개 읽기 여부만. PUBLIC_READ=false 여도 401 안 냄 (데이터 없음)."""
    if principal is None:
        return MeOut(authenticated=False, public_read=settings.PUBLIC_READ)
    return MeOut(authenticated=True, public_read=settings.PUBLIC_READ,
                 username=principal.username, role=principal.role, csrf_token=principal.csrf_token)

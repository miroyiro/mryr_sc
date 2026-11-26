"""(a) 관리 GUI 인증·CSRF·역할·공개 읽기 — DB 없이 FakeStore 로.

(b)(c) 의 실제 읽기/쓰기 라우트가 생기기 전이라, 같은 의존성(ReaderDep·EditorDep·AdminDep)을 쓰는
검사용 라우트(_probe)를 테스트 앱에만 붙여서 확인한다.
"""
from datetime import timedelta

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.admin import auth_router
from src.admin.deps import AdminDep, EditorDep, ReaderDep, get_store
from src.admin.security import hash_password, login_limiter, verify_password
from src.config.settings import settings
from tests.admin_fake import PASSWORD, FakeStore

probe = APIRouter(prefix="/admin/api/_probe")


@probe.get("/read")
async def probe_read(p: ReaderDep):
    return {"public": p is None}


@probe.post("/read-misused")   # 실수로 쓰기 라우트에 ReaderDep 만 붙인 경우
async def probe_read_post(p: ReaderDep):
    return {"public": p is None}


@probe.post("/edit")
async def probe_edit(_: EditorDep):
    return {"ok": True}


@probe.post("/admin-only")
async def probe_admin(_: AdminDep):
    return {"ok": True}


@pytest.fixture
def store():
    s = FakeStore()
    s.add_user("ed", "editor")
    s.add_user("boss", "admin")
    s.add_user("gone", "admin", active=False)
    return s


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_READ", False)
    login_limiter.reset()
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(probe)
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def login(client, username, password=PASSWORD):
    return client.post("/admin/api/login", json={"username": username, "password": password})


# --- 비밀번호 해시 ---
def test_password_hash_roundtrip_and_salt():
    h1, h2 = hash_password("abc-123-xyz!"), hash_password("abc-123-xyz!")
    assert h1 != h2                                   # salt 가 달라서 같은 비번도 다른 해시
    assert verify_password("abc-123-xyz!", h1)
    assert not verify_password("abc-123-xyz?", h1)
    assert not verify_password("x", "garbage")        # 깨진 형식 → 예외 대신 False


# --- 로그인 ---
def test_login_sets_secure_cookie_flags_and_hides_hash(client):
    r = login(client, "ed")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "editor" and body["csrf_token"]
    assert "password" not in r.text and "scrypt$" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/admin" in cookie
    assert "secure" not in cookie                    # COOKIE_SECURE 기본 false (로컬 http)


def test_cookie_secure_flag_follows_env(client, monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    assert "secure" in login(client, "ed").headers["set-cookie"].lower()


def test_login_failures_are_indistinguishable(client):
    wrong = login(client, "ed", "nope-nope-nope")
    unknown = login(client, "nobody", "nope-nope-nope")
    inactive = login(client, "gone")
    assert wrong.status_code == unknown.status_code == inactive.status_code == 401
    assert wrong.json() == unknown.json() == inactive.json()


def test_login_lockout_after_5_failures(client, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(login_limiter, "clock", lambda: t[0])
    for _ in range(5):
        assert login(client, "ed", "wrong-wrong").status_code == 401
    assert login(client, "ed").status_code == 429      # 맞는 비번이어도 잠김
    assert login(client, "boss").status_code == 200    # 다른 계정은 영향 없음
    t[0] += 15 * 60
    assert login(client, "ed").status_code == 200      # 15분 뒤 풀림


# --- 비로그인 ---
def test_anonymous_write_is_401(client):
    assert client.post("/admin/api/_probe/edit").status_code == 401
    assert client.post("/admin/api/_probe/admin-only").status_code == 401


def test_public_read_false_anonymous_read_is_401(client):
    assert client.get("/admin/api/_probe/read").status_code == 401


def test_public_read_true_allows_get_only(client, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_READ", True)
    r = client.get("/admin/api/_probe/read")
    assert r.status_code == 200 and r.json() == {"public": True}
    assert client.post("/admin/api/_probe/edit").status_code == 401   # 쓰기는 PUBLIC_READ 와 무관
    # ReaderDep 를 POST 에 잘못 붙여도 비로그인은 통과 못 함 (공개 읽기 = GET 만)
    assert client.post("/admin/api/_probe/read-misused").status_code == 401


def test_me_anonymous_has_no_secret(client):
    r = client.get("/admin/api/me")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False, "public_read": False,
                        "username": None, "role": None, "csrf_token": None}


# --- CSRF · 역할 ---
def test_csrf_missing_or_wrong_is_403(client):
    csrf = login(client, "ed").json()["csrf_token"]
    assert client.post("/admin/api/_probe/edit").status_code == 403
    assert client.post("/admin/api/_probe/edit", headers={"X-CSRF-Token": "x" + csrf}).status_code == 403
    assert client.post("/admin/api/_probe/edit", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_editor_cannot_do_admin_action(client):
    csrf = login(client, "ed").json()["csrf_token"]
    assert client.post("/admin/api/_probe/admin-only", headers={"X-CSRF-Token": csrf}).status_code == 403


def test_admin_can_do_editor_and_admin_actions(client):
    csrf = login(client, "boss").json()["csrf_token"]
    h = {"X-CSRF-Token": csrf}
    assert client.post("/admin/api/_probe/edit", headers=h).status_code == 200
    assert client.post("/admin/api/_probe/admin-only", headers=h).status_code == 200


def test_logged_in_reader_ok_even_if_public_read_false(client):
    login(client, "ed")
    r = client.get("/admin/api/_probe/read")
    assert r.status_code == 200 and r.json() == {"public": False}


# --- 로그아웃 · 만료 ---
def test_logout_requires_csrf_and_invalidates_session(client, store):
    csrf = login(client, "ed").json()["csrf_token"]
    cookie = client.cookies.get("mryr_admin")
    assert client.post("/admin/api/logout").status_code == 403         # CSRF 없이 로그아웃 X
    assert client.post("/admin/api/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert store.sessions == {}
    # 지워진 쿠키를 다시 실어 보내도 무효
    client.cookies.set("mryr_admin", cookie, path="/admin")
    assert client.get("/admin/api/me").json()["authenticated"] is False
    assert client.post("/admin/api/_probe/edit", headers={"X-CSRF-Token": csrf}).status_code == 401


def test_expired_session_is_anonymous(client, store):
    csrf = login(client, "ed").json()["csrf_token"]
    for s in store.sessions.values():
        s.expires_at -= timedelta(hours=settings.SESSION_TTL_HOURS + 1)
    assert client.post("/admin/api/_probe/edit", headers={"X-CSRF-Token": csrf}).status_code == 401


def test_deactivated_user_session_is_anonymous(client, store):
    csrf = login(client, "ed").json()["csrf_token"]
    store.users["ed"].is_active = False
    assert client.post("/admin/api/_probe/edit", headers={"X-CSRF-Token": csrf}).status_code == 401


# --- 기존 /internal 동작 그대로 ---
def test_internal_still_requires_internal_key():
    from src.main import app
    c = TestClient(app)
    assert c.get("/internal/pipeline/sources").status_code == 401
    # 관리 세션 쿠키로는 /internal 통과 못 함 (경로·인증 분리)
    c.cookies.set("mryr_admin", "anything")
    assert c.get("/internal/pipeline/sources").status_code == 401

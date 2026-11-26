"""(b) 읽기 API·화이트리스트·화면 서빙·/admin 500 고정 — 실제 앱(src.main.app) + 가짜 저장소, DB 없음."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.admin import read_router
from src.admin.deps import get_store
from src.admin.security import login_limiter
from src.admin.web import ADMIN_500
from src.config.database import get_db
from src.config.settings import settings
from src.main import app
from tests.admin_fake import LEAK, PASSWORD, FakeReadStore

READ_PATHS = ["/admin/api/dashboard", "/admin/api/sources", "/admin/api/targets", "/admin/api/targets/1"]

# 비로그인 응답에 '키 이름'으로도 나오면 안 되는 것
PUBLIC_FORBIDDEN_KEYS = {
    "raw_data", "content", "config", "base_url", "url", "value", "x_user_id", "last_seen_external_id",
    "admin_note", "error_message", "message", "stack", "target", "api_key", "token", "csrf_token",
    "password_hash", "ip", "images", "event_data", "description", "verified_by", "monthly_budget_usd",
}
# 비로그인 응답 '값' 어디에도 나오면 안 되는 패턴: 심어둔 표식·URL·IP·스택·키
PUBLIC_FORBIDDEN_VALUES = [
    re.compile(re.escape(LEAK)), re.compile(r"https?://"), re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"),
    re.compile(r"Traceback"), re.compile(r"sk-"), re.compile(r"/srv/"),
]
# 로그인해도 안 나가는 것
ALWAYS_FORBIDDEN_KEYS = {"raw_data", "content", "stack", "error_message", "message", "config",
                         "password_hash", "last_seen_external_id", "api_key"}


def walk(obj, path="$"):
    """JSON 을 재귀로 돌며 (경로, 키, 값) 을 전부 내놓음."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, k, v
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def leaks(body, forbidden_keys, forbidden_values):
    found = []
    for path, key, value in walk(body):
        if key in forbidden_keys:
            found.append(f"{path}.{key} (금지 키)")
        if isinstance(value, str) and any(p.search(value) for p in forbidden_values):
            found.append(f"{path}.{key}={value!r} (금지 값)")
    return found


@pytest.fixture
def store():
    s = FakeReadStore()
    s.add_user("ed", "editor")
    return s


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_READ", True)
    login_limiter.reset()
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app, raise_server_exceptions=False)   # 500 을 예외 대신 응답으로 받기
    app.dependency_overrides.clear()


def login(client):
    r = client.post("/admin/api/login", json={"username": "ed", "password": PASSWORD})
    assert r.status_code == 200
    return r.json()["csrf_token"]


# --- 금지 필드 0건 ---
def test_leak_detector_itself_works():
    """검사기가 진짜 잡는지: 금지 키·값을 넣은 가짜 응답은 걸려야 함."""
    assert leaks({"a": [{"raw_data": 1}]}, PUBLIC_FORBIDDEN_KEYS, PUBLIC_FORBIDDEN_VALUES)
    assert leaks({"a": {"b": "see http://10.1.2.3"}}, PUBLIC_FORBIDDEN_KEYS, PUBLIC_FORBIDDEN_VALUES)
    assert not leaks({"a": {"handle": "@ok"}}, PUBLIC_FORBIDDEN_KEYS, PUBLIC_FORBIDDEN_VALUES)


@pytest.mark.parametrize("path", READ_PATHS + ["/admin/api/targets/2"])
def test_public_responses_have_no_forbidden_fields(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert leaks(r.json(), PUBLIC_FORBIDDEN_KEYS, PUBLIC_FORBIDDEN_VALUES) == []
    assert LEAK not in r.text


def test_public_target_shows_x_handle_only(client):
    data = client.get("/admin/api/targets").json()["data"]
    by_type = {t["target_type"]: t for t in data}
    assert by_type["x_account"]["handle"] == "@miroyiro_official"
    assert by_type["board"]["handle"] is None          # URL 대상은 비로그인에게 값 숨김


def test_public_dashboard_has_no_error_counts(client):
    assert "error_counts" not in client.get("/admin/api/dashboard").json()


@pytest.mark.parametrize("path", READ_PATHS)
def test_logged_in_responses_still_hide_raw_and_stack(client, path):
    login(client)
    r = client.get(path)
    assert r.status_code == 200
    assert leaks(r.json(), ALWAYS_FORBIDDEN_KEYS, [re.compile("Traceback"), re.compile("sk-"),
                                                   re.compile(r"10\.0\.0\.5")]) == []


def test_logged_in_gets_admin_fields(client):
    login(client)
    dash = client.get("/admin/api/dashboard").json()
    assert dash["error_counts"] == [{"type": "http_429", "count": 2}]
    src = {s["name"]: s for s in client.get("/admin/api/sources").json()}
    assert src["x"]["monthly_budget_usd"] == 5.0
    t = client.get("/admin/api/targets/2").json()
    assert t["value"].startswith("https://") and "admin_note" in t


# --- PUBLIC_READ=false ---
@pytest.mark.parametrize("path", READ_PATHS)
def test_public_read_false_anonymous_is_401(client, monkeypatch, path):
    monkeypatch.setattr(settings, "PUBLIC_READ", False)
    assert client.get(path).status_code == 401


def test_public_read_false_logged_in_ok(client, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_READ", False)
    login(client)
    assert client.get("/admin/api/dashboard").status_code == 200


# --- 빈 상태 · 404 ---
def test_empty_dashboard_uses_process_start_time(store, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_READ", True)
    app.dependency_overrides[get_store] = lambda: FakeReadStore(empty=True)
    try:
        r = TestClient(app).get("/admin/api/dashboard")
    finally:
        app.dependency_overrides.clear()
    body = r.json()
    assert r.status_code == 200
    assert body["source_counts"] == [] and body["recent_jobs"] == []
    assert body["started_at"].startswith(read_router.PROCESS_STARTED_AT.isoformat()[:19])


def test_unknown_target_404(client):
    assert client.get("/admin/api/targets/999").status_code == 404


# --- /admin 500 고정 JSON ---
@pytest.mark.parametrize("logged_in", [False, True])
def test_admin_500_body_is_fixed_without_internal_details(store, client, logged_in):
    if logged_in:
        login(client)
    store.fail = True
    r = client.get("/admin/api/dashboard")
    assert r.status_code == 500
    assert r.json() == ADMIN_500
    for bad in (LEAK, "/srv/", "secret.py", "hunter2", "Traceback", "RuntimeError", "password"):
        assert bad not in r.text


def test_non_admin_500_unchanged(client):
    """/admin 밖은 기존 Starlette 기본 응답 그대로 (고정 JSON 은 /admin 만)."""
    async def broken_db():
        raise RuntimeError("db secret /srv/x")
        yield  # noqa — 제너레이터 의존성 모양
    app.dependency_overrides[get_db] = broken_db
    r = client.get("/health")
    assert r.status_code == 500 and r.text == "Internal Server Error"


# --- 화면 서빙 · CSP ---
STATIC = Path(__file__).parent.parent / "src" / "admin" / "static"


def test_admin_page_served_with_security_headers(client):
    r = client.get("/admin")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/admin/static/app.js").status_code == 200
    assert client.get("/admin/api/me").headers["cache-control"] == "no-store"


def test_frontend_has_no_inline_script_style_or_innerhtml():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)    # src 없는 <script> = 인라인
    assert "<style" not in html and " style=" not in html and "javascript:" not in html
    assert not re.search(r"\son\w+=", html)                        # onclick= 같은 인라인 핸들러
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    code = "\n".join(line.split("//")[0] for line in js.splitlines())   # 주석 제외
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert bad not in code

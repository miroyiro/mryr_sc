"""(c) 쓰기 2개 — 메모(editor 이상) · X 대상 verify(admin, 월 예산 없으면 409). 실제 앱 + FakeReadStore, DB 없음.

공통 권한(401·CSRF 403·역할 403)은 test_admin_auth.py. 여기는 각 쓰기의 내용 규칙.
"""
import pytest
from fastapi.testclient import TestClient

from src.admin.deps import get_store
from src.admin.security import login_limiter
from src.admin.write_router import budget_is_set
from src.config.settings import settings
from src.main import app
from tests.admin_fake import PASSWORD, FakeReadStore


@pytest.fixture
def store():
    s = FakeReadStore()
    s.add_user("ed", "editor")
    s.add_user("boss", "admin")
    return s


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_READ", False)
    login_limiter.reset()
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def as_user(client, username) -> dict:
    r = client.post("/admin/api/login", json={"username": username, "password": PASSWORD})
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def x_target(store):
    return store.target_rows[0][0]       # id 1, x_account, source x(id 1)


# --- 메모 ---
def test_editor_saves_and_clears_note(client, store):
    h = as_user(client, "ed")
    r = client.patch("/admin/api/targets/1/note", json={"admin_note": "  공식 계정 확인함  "}, headers=h)
    assert r.status_code == 200 and r.json()["admin_note"] == "공식 계정 확인함"
    assert x_target(store).admin_note == "공식 계정 확인함"
    r = client.patch("/admin/api/targets/1/note", json={"admin_note": "   "}, headers=h)
    assert r.json()["admin_note"] is None              # 공백만 = 메모 지움


def test_note_longer_than_500_is_422(client, store):
    h = as_user(client, "ed")
    r = client.patch("/admin/api/targets/1/note", json={"admin_note": "가" * 501}, headers=h)
    assert r.status_code == 422
    assert x_target(store).admin_note == "메모 LEAK-SENTINEL"


def test_note_unknown_target_404(client):
    h = as_user(client, "ed")
    assert client.patch("/admin/api/targets/999/note", json={"admin_note": "x"}, headers=h).status_code == 404


# --- verify ---
def test_admin_verify_records_who_and_when(client, store):
    h = as_user(client, "boss")
    r = client.post("/admin/api/targets/1/verify", headers=h)
    assert r.status_code == 200
    body = r.json()
    boss_id = store.users["boss"].id
    assert body["is_verified"] is True and body["verified_by"] == boss_id and body["verified_at"]
    t = x_target(store)
    assert t.is_verified is True and t.verified_by == boss_id and t.verified_at is not None


@pytest.mark.parametrize("cfg", [None, {}, {"monthly_budget_usd": None}, {"monthly_budget_usd": 0},
                                 {"monthly_budget_usd": "5"}, {"monthly_budget_usd": True}])
def test_verify_without_budget_is_409_and_unchanged(client, store, cfg):
    store.source_by_id[1].config = cfg
    h = as_user(client, "boss")
    r = client.post("/admin/api/targets/1/verify", headers=h)
    assert r.status_code == 409
    t = x_target(store)
    assert t.is_verified is False and t.verified_by is None and t.verified_at is None


def test_verify_non_x_target_is_400(client, store):
    h = as_user(client, "boss")
    assert client.post("/admin/api/targets/2/verify", headers=h).status_code == 400   # board 대상
    assert store.target_rows[1][0].is_verified is False


def test_verify_unknown_target_404(client):
    h = as_user(client, "boss")
    assert client.post("/admin/api/targets/999/verify", headers=h).status_code == 404


def test_editor_verify_is_403_even_with_budget(client, store):
    h = as_user(client, "ed")
    assert client.post("/admin/api/targets/1/verify", headers=h).status_code == 403
    assert x_target(store).is_verified is False


def test_budget_rule():
    assert budget_is_set({"monthly_budget_usd": 5}) and budget_is_set({"monthly_budget_usd": 0.5})
    for cfg in (None, {}, {"monthly_budget_usd": 0}, {"monthly_budget_usd": -1},
                {"monthly_budget_usd": "5"}, {"monthly_budget_usd": True}):
        assert not budget_is_set(cfg)


# --- 범위 밖 쓰기는 없음 ---
@pytest.mark.parametrize("method,path", [
    ("POST", "/admin/api/targets"), ("DELETE", "/admin/api/targets/1"),
    ("PATCH", "/admin/api/targets/1"), ("PATCH", "/admin/api/sources/1"),
])
def test_out_of_scope_writes_do_not_exist(client, method, path):
    h = as_user(client, "boss")
    assert client.request(method, path, headers=h, json={}).status_code in (404, 405)

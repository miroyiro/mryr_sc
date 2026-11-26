"""관리 GUI 테스트용 가짜 저장소 — AdminStore 와 같은 메서드를 메모리로. 실제 DB 없이 권한 로직만 검사."""
from datetime import UTC, datetime
from types import SimpleNamespace

from src.admin.security import hash_password

PASSWORD = "correct-horse-battery"   # 테스트 전용 값
_HASH = hash_password(PASSWORD)      # scrypt 는 느려서 모듈 로드 때 1번만


class FakeStore:
    def __init__(self):
        self.users: dict[str, SimpleNamespace] = {}
        self.sessions: dict[str, SimpleNamespace] = {}   # token_hash → 세션

    def add_user(self, username: str, role: str, *, active: bool = True) -> SimpleNamespace:
        u = SimpleNamespace(id=len(self.users) + 1, username=username, password_hash=_HASH,
                            role=role, is_active=active)
        self.users[username] = u
        return u

    async def get_user_by_username(self, username):
        return self.users.get(username)

    async def create_session(self, user_id, token_hash, csrf_token, expires_at, now):
        self.sessions[token_hash] = SimpleNamespace(admin_user_id=user_id, csrf_token=csrf_token,
                                                    expires_at=expires_at)

    async def get_session_user(self, token_hash, now):
        s = self.sessions.get(token_hash)
        if s is None or s.expires_at <= now:
            return None
        user = next(u for u in self.users.values() if u.id == s.admin_user_id)
        return (s, user) if user.is_active else None

    async def delete_session(self, token_hash):
        self.sessions.pop(token_hash, None)


# --- 읽기 데이터 (b) ---
# 금지 필드에는 전부 LEAK 표식을 심는다 → 응답 어디에든 'LEAK' 가 보이면 화이트리스트가 뚫린 것
LEAK = "LEAK-SENTINEL"
T0 = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)


def _source(id_, name, **kw):
    return SimpleNamespace(
        id=id_, name=name, type="api", enabled=True, auto_publish=False, description="설명",
        base_url=f"http://10.0.0.5:9000/{LEAK}",
        config={"monthly_budget_usd": 5, "api_key": f"sk-{LEAK}", "internal_url": f"http://{LEAK}"}, **kw)


def _target(id_, source_id, ttype, value):
    return SimpleNamespace(
        id=id_, source_id=source_id, target_type=ttype, value=value, status="active", is_verified=False,
        x_user_id=f"{LEAK}-xid", crawl_interval_sec=3600, last_crawled_at=T0,
        last_seen_external_id=f"{LEAK}-ext", admin_note=f"메모 {LEAK}", verified_by=None, verified_at=None,
        created_at=T0, updated_at=T0)


def _job(id_, source_id):
    return SimpleNamespace(
        id=id_, source_id=source_id, status="failed", total_count=3, collected_count=2, duplicate_count=1,
        error_count=1, started_at=T0, finished_at=T0, created_at=T0,
        target=f"https://internal.example/{LEAK}", error_message=f"Traceback {LEAK} /srv/app/x.py key=sk-{LEAK}",
        raw_data={"content": LEAK})


class FakeReadStore(FakeStore):
    def __init__(self, *, empty: bool = False, fail: bool = False):
        super().__init__()
        self.fail = fail
        x, animate = _source(1, "x"), _source(2, "animate")
        self.sources = [] if empty else [(animate, "completed"), (x, "failed")]
        self.counts = [] if empty else [("animate", 12), ("x", 0)]
        self.jobs = [] if empty else [(_job(10, 1), "x")]
        self.errors = [] if empty else [("http_429", 2)]
        self.target_rows = [] if empty else [
            (_target(1, 1, "x_account", "@miroyiro_official"), "x"),
            (_target(2, 2, "board", f"https://www.animate-onlineshop.co.kr/board?{LEAK}"), "animate"),
        ]

    def _check(self):
        if self.fail:
            raise RuntimeError(f"db down at /srv/app/secret.py password=hunter2 {LEAK}")

    async def first_job_at(self):
        self._check()
        return T0 if self.jobs else None

    async def sources_with_last_status(self):
        self._check()
        return self.sources

    async def collected_counts(self):
        self._check()
        return self.counts

    async def recent_jobs(self, limit=10):
        self._check()
        return self.jobs[:limit]

    async def error_type_counts(self):
        self._check()
        return self.errors

    async def targets(self, page, source_id):
        self._check()
        rows = [r for r in self.target_rows if source_id is None or r[0].source_id == source_id]
        return rows[page.offset: page.offset + page.limit], len(rows)

    async def target(self, target_id):
        self._check()
        return next((r for r in self.target_rows if r[0].id == target_id), None)

"""관리 GUI 테스트용 가짜 저장소 — AdminStore 와 같은 메서드를 메모리로. 실제 DB 없이 권한 로직만 검사."""
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

"""관리 GUI 의 DB 접근을 한 클래스에 모음.

라우터는 AdminStore 메서드만 부름 → 테스트는 get_store 의존성을 가짜 저장소로 바꿔서 실제 DB 없이 돈다.
여기 SQL 은 실제 Postgres 에서만 검증 가능 (pytest 대상 아님).
"""
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AdminSession, AdminUser


class AdminStore:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- 계정 ---
    async def get_user_by_username(self, username: str) -> AdminUser | None:
        return await self.db.scalar(select(AdminUser).where(AdminUser.username == username))

    async def create_user(self, username: str, password_hash: str, role: str) -> AdminUser:
        user = AdminUser(username=username, password_hash=password_hash, role=role, is_active=True)
        self.db.add(user)
        await self.db.commit()
        return user

    async def update_user(self, user: AdminUser, *, password_hash: str, role: str) -> None:
        """비밀번호 재설정 → 그 계정의 기존 세션 전부 삭제 (유출된 세션도 같이 끊김)."""
        user.password_hash = password_hash
        user.role = role
        await self.db.execute(delete(AdminSession).where(AdminSession.admin_user_id == user.id))
        await self.db.commit()

    # --- 세션 ---
    async def create_session(self, user_id: int, token_hash: str, csrf_token: str,
                             expires_at: datetime, now: datetime) -> None:
        # 로그인할 때마다 만료된 세션 청소 → 테이블이 계속 커지지 않게
        await self.db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
        self.db.add(AdminSession(admin_user_id=user_id, token_hash=token_hash,
                                 csrf_token=csrf_token, expires_at=expires_at))
        await self.db.commit()

    async def get_session_user(self, token_hash: str, now: datetime) -> tuple[AdminSession, AdminUser] | None:
        """유효한 세션만: 만료 전 + 계정 활성. 비활성화된 계정은 기존 세션도 즉시 무효."""
        stmt = (
            select(AdminSession, AdminUser)
            .join(AdminUser, AdminUser.id == AdminSession.admin_user_id)
            .where(AdminSession.token_hash == token_hash,
                   AdminSession.expires_at > now,
                   AdminUser.is_active.is_(True))
        )
        row = (await self.db.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def delete_session(self, token_hash: str) -> None:
        await self.db.execute(delete(AdminSession).where(AdminSession.token_hash == token_hash))
        await self.db.commit()

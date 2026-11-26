"""관리 GUI 의 DB 접근을 한 클래스에 모음.

라우터는 AdminStore 메서드만 부름 → 테스트는 get_store 의존성을 가짜 저장소로 바꿔서 실제 DB 없이 돈다.
여기 SQL 은 실제 Postgres 에서만 검증 가능 (pytest 대상 아님).
"""
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AdminSession, AdminUser, RawItem, ScrapeError, ScrapeJob, ScrapeSource, ScrapeTarget
from src.schemas.common import PageParams


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

    # --- 읽기 (b). 모델 객체를 돌려주고, 어떤 필드를 내보낼지는 read_router 의 스키마 변환이 정함 ---
    async def first_job_at(self) -> datetime | None:
        return await self.db.scalar(select(func.min(ScrapeJob.created_at)))

    async def sources_with_last_status(self) -> list[tuple[ScrapeSource, str | None]]:
        last_status = (
            select(ScrapeJob.status).where(ScrapeJob.source_id == ScrapeSource.id)
            .order_by(ScrapeJob.id.desc()).limit(1).scalar_subquery()
        )
        rows = await self.db.execute(select(ScrapeSource, last_status).order_by(ScrapeSource.name))
        return [(r[0], r[1]) for r in rows]

    async def collected_counts(self) -> list[tuple[str, int]]:
        """소스별 raw_item 건수. 0건 소스도 나오게 LEFT JOIN."""
        stmt = (
            select(ScrapeSource.name, func.count(RawItem.id))
            .outerjoin(RawItem, RawItem.source_id == ScrapeSource.id)
            .group_by(ScrapeSource.name).order_by(ScrapeSource.name)
        )
        return [(r[0], int(r[1])) for r in await self.db.execute(stmt)]

    async def recent_jobs(self, limit: int = 10) -> list[tuple[ScrapeJob, str]]:
        stmt = (
            select(ScrapeJob, ScrapeSource.name).join(ScrapeSource, ScrapeSource.id == ScrapeJob.source_id)
            .order_by(ScrapeJob.id.desc()).limit(limit)
        )
        return [(r[0], r[1]) for r in await self.db.execute(stmt)]

    async def error_type_counts(self) -> list[tuple[str, int]]:
        """미해결 에러의 유형별 건수 (로그인 전용)."""
        stmt = (
            select(ScrapeError.type, func.count()).where(ScrapeError.status == "unresolved")
            .group_by(ScrapeError.type).order_by(func.count().desc())
        )
        return [(r[0], int(r[1])) for r in await self.db.execute(stmt)]

    async def targets(self, page: PageParams, source_id: int | None) -> tuple[list[tuple[ScrapeTarget, str]], int]:
        base = select(ScrapeTarget, ScrapeSource.name).join(ScrapeSource, ScrapeSource.id == ScrapeTarget.source_id)
        if source_id is not None:
            base = base.where(ScrapeTarget.source_id == source_id)
        total = await self.db.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.db.execute(base.order_by(ScrapeTarget.id.desc()).offset(page.offset).limit(page.limit))
        return [(r[0], r[1]) for r in rows], int(total or 0)

    # --- 쓰기 (c). 메모·verify 만 ---
    async def target_with_source(self, target_id: int) -> tuple[ScrapeTarget, ScrapeSource] | None:
        """verify 는 소스 config(monthly_budget_usd)까지 봐야 해서 소스 객체를 같이 돌려줌."""
        stmt = (
            select(ScrapeTarget, ScrapeSource).join(ScrapeSource, ScrapeSource.id == ScrapeTarget.source_id)
            .where(ScrapeTarget.id == target_id)
        )
        row = (await self.db.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def set_note(self, target: ScrapeTarget, note: str | None) -> None:
        target.admin_note = note
        await self.db.commit()

    async def mark_verified(self, target: ScrapeTarget, *, user_id: int, at: datetime) -> None:
        target.is_verified = True
        target.verified_by = user_id
        target.verified_at = at
        await self.db.commit()

    async def target(self, target_id: int) -> tuple[ScrapeTarget, str] | None:
        stmt = (
            select(ScrapeTarget, ScrapeSource.name).join(ScrapeSource, ScrapeSource.id == ScrapeTarget.source_id)
            .where(ScrapeTarget.id == target_id)
        )
        row = (await self.db.execute(stmt)).first()
        return (row[0], row[1]) if row else None

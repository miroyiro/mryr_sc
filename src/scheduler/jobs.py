"""스케줄이 실제로 실행하는 함수."""
import logging

from src.config.database import SessionLocal
from src.repositories import job_repository, schedule_repository, source_repository, target_repository
from src.services.collect_service import run_scrape_job
from src.utils.time import now_kst

log = logging.getLogger(__name__)


async def run_schedule(schedule_id: int) -> None:
    """스케줄 1개 → 대상마다 scrape_job 생성 → 순서대로 실행 (같은 소스는 gate 가 간격 보장).
    target_id 가 NULL 인 스케줄 = 그 소스의 검증된 active 대상 전부 (API 소스는 대상 없이 1번)."""
    async with SessionLocal() as session:
        s = await schedule_repository.get(session, schedule_id)
        if s is None or not s.enabled:
            return
        source = await source_repository.get(session, s.source_id)
        if source is None or not source.enabled:
            return
        if s.target_id:
            targets = [await target_repository.get(session, s.target_id)]
        else:
            targets = await target_repository.list_collectable(session, source.id) or [None]
        job_ids = []
        for t in targets:
            job = await job_repository.create_scrape_job(
                session, source_id=source.id, target_id=t.id if t else None, schedule_id=s.id,
                target=t.value if t else None,
            )
            job_ids.append(job.id)
        await schedule_repository.mark_run(session, s, at=now_kst(), next_run_at=None)
        await session.commit()

    for job_id in job_ids:
        await run_scrape_job(job_id)


async def resume_stale_jobs() -> None:
    """서버 재시작 후 남은 queued 잡 처리 (BackgroundTasks 는 프로세스와 같이 죽음)."""
    async with SessionLocal() as session:
        jobs = await job_repository.list_stale_queued(session)
    for j in jobs:
        await run_scrape_job(j.id)

"""APScheduler 시작/정지 (공통 파일 — 명주 소유). 3.x AsyncIOScheduler.

- 프로세스 1개에서만 돌린다 (미니PC 컨테이너 1개). 여러 개 띄우면 같은 잡이 중복 실행됨
  → 그래도 job 선점(claim) 이 조건부 UPDATE 라서 실제 수집은 한 번만.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.utils.time import KST

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    timezone=KST,
    job_defaults={
        "coalesce": True,          # 밀린 실행 여러 번 → 1번으로
        "max_instances": 1,        # 같은 스케줄이 겹쳐 돌지 않게
        "misfire_grace_time": 300,
    },
)


async def start() -> None:
    from src.scheduler.loader import load_all
    await load_all()
    scheduler.start()
    log.info("scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)

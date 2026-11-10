"""scrape_schedule 행 → APScheduler 잡 등록. 스케줄 API 가 바뀌면 reload_one 호출."""
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config.database import SessionLocal
from src.models import ScrapeSchedule
from src.models.enums import ScheduleType
from src.repositories import schedule_repository
from src.scheduler.jobs import run_schedule
from src.scheduler.scheduler import scheduler
from src.utils.time import KST


def _job_id(schedule_id: int) -> str:
    return f"schedule:{schedule_id}"


def _trigger(s: ScrapeSchedule):
    if s.schedule_type == ScheduleType.CRON:
        return CronTrigger.from_crontab(s.cron_expression, timezone=KST)
    return IntervalTrigger(minutes=s.interval_minutes, timezone=KST)


def register(s: ScrapeSchedule) -> None:
    scheduler.add_job(run_schedule, trigger=_trigger(s), id=_job_id(s.id), args=[s.id], replace_existing=True)


def unregister(schedule_id: int) -> None:
    job = scheduler.get_job(_job_id(schedule_id))
    if job:
        job.remove()


async def load_all() -> None:
    async with SessionLocal() as session:
        for s in await schedule_repository.list_runnable(session):
            register(s)


async def reload_one(schedule_id: int) -> None:
    async with SessionLocal() as session:
        s = await schedule_repository.get(session, schedule_id)
    if s is None or not s.enabled:
        unregister(schedule_id)
    else:
        register(s)

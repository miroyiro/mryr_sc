"""수집 실행: scrape_job 1개 → 컬렉터 → raw_item. (명주)

흐름
  1) queued → running 을 조건부 UPDATE 로 '선점' (중복 실행 방지)
  2) 컬렉터 실행 (registry 로 소스별 클래스 선택)
  3) raw_item upsert (UNIQUE + hash) → collected / duplicate 카운트
  4) target.last_seen_external_id 갱신 (증분 기준)
  5) 성공 시 process_job 생성 → process_service 실행
  실패는 scrape_error 에 기록, job.status = failed
"""
import logging

from src.collectors.registry import CollectorNotImplemented, build_collector
from src.collectors.scraping.base_scraper import RobotsDisallowed
from src.config.database import SessionLocal
from src.models import ScrapeJob
from src.models.enums import ErrorJobType, ScrapeJobStatus
from src.repositories import error_repository, job_repository, raw_item_repository, source_repository, target_repository
from src.utils.hashing import sha256_hex
from src.utils.time import now_kst

log = logging.getLogger(__name__)


async def run_scrape_job(job_id: int) -> None:
    """BackgroundTasks / 스케줄러에서 호출. 자기 세션을 직접 연다 (요청 세션은 이미 닫혔을 수 있음)."""
    async with SessionLocal() as session:
        if not await job_repository.claim_scrape_job(session, job_id):
            log.info("scrape_job %s already taken or not queued", job_id)
            return
        await session.commit()

        job: ScrapeJob = await job_repository.get_scrape_job(session, job_id)
        source = await source_repository.get(session, job.source_id)
        target = await target_repository.get(session, job.target_id) if job.target_id else None

        collector = None
        try:
            if target is not None and not target.is_verified:
                raise PermissionError("unverified target — is_verified 대상만 수집")
            collector = build_collector(source, target)
            result = await collector.collect(target)

            collected = duplicate = 0
            for item in result.items:
                h = sha256_hex(item.url, item.title, item.content, item.published_at)
                r = await raw_item_repository.upsert(
                    session, source_id=source.id, scrape_job_id=job.id, external_id=item.external_id,
                    hash_=h, url=item.url, title=item.title, content=item.content, author=item.author,
                    images=item.images, published_at=item.published_at, raw_data=item.raw_data,
                )
                if r.inserted or r.changed:
                    collected += 1
                else:
                    duplicate += 1

            job.total_count = len(result.items)
            job.collected_count = collected
            job.duplicate_count = duplicate
            if target is not None:
                await target_repository.mark_crawled(
                    session, target, at=now_kst(), last_seen_external_id=result.last_seen_external_id
                )
            await job_repository.finish_scrape_job(session, job, status=ScrapeJobStatus.COMPLETED)
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — 잡 단위로 잡아서 기록
            await session.rollback()
            job = await job_repository.get_scrape_job(session, job_id)
            job.error_count += 1
            await error_repository.record(
                session, job_type=ErrorJobType.SCRAPE, job_id=job_id, error_type=_error_type(exc), exc=exc,
            )
            await job_repository.finish_scrape_job(session, job, status=ScrapeJobStatus.FAILED,
                                                   error_message=str(exc)[:1000])
            await session.commit()
            log.exception("scrape_job %s failed", job_id)
            return
        finally:
            if collector is not None:
                await collector.aclose()

    if collected:
        from src.services.process_service import run_process_for_scrape_job  # 순환 import 방지
        await run_process_for_scrape_job(job_id)


def _error_type(exc: Exception) -> str:
    if isinstance(exc, CollectorNotImplemented):
        return "collector_not_implemented"
    if isinstance(exc, RobotsDisallowed):
        return "robots_disallow"
    if isinstance(exc, PermissionError):
        return "unverified_target"
    name = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"http_{status}" if status else name.lower()

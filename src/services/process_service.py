"""가공 실행: raw_item → processed_item (명주).

- 소스별 파서 선택 → ParsedItem
- name_matcher 로 artist/anime 후보 + confidence
- processed_item upsert (uq_processed_raw: 재처리 = UPDATE, 검수 끝난 건 보존)
- scrape_source.auto_publish = TRUE (kopis, anissia) 면 바로 publish
- 카탈로그 보강 소스(laftel, aniplus 동시방영)는 processed_item 을 거치지 않음 → catalog_service
"""
import logging
import time

from src.clients.backend_client import get_backend
from src.config.database import SessionLocal
from src.models.enums import ErrorJobType, ProcessJobStatus, TargetType
from src.parsers.animate_parser import AnimateEventParser
from src.parsers.anissia_parser import AnissiaParser
from src.parsers.base_parser import BaseParser
from src.parsers.event_parser import EventParser
from src.parsers.kopis_parser import KopisParser
from src.parsers.news_parser import NewsParser
from src.parsers.name_matcher import CatalogName, NameMatcher
from src.repositories import (
    error_repository, job_repository, processed_item_repository, raw_item_repository, source_repository,
    target_repository,
)
from src.utils.time import now_kst

log = logging.getLogger(__name__)

# 소스 → 파서. 준현 소스(kopis/anissia/x/umj)용 파서는 같이 정해서 추가
PARSERS: dict[str, BaseParser] = {
    "animate": AnimateEventParser(),   # raw_data(라벨·기간·장소) 구조화된 전용 파서
    "aniplus": NewsParser(),
    "anissia": AnissiaParser(),        # 방영 (작품 × 방영일)
    "kopis": KopisParser(),            # 내한 공연
    "umj": NewsParser(),
    "x": EventParser(main_category="anime"),   # TODO: 아티스트 계정이면 jpop — target.artist_id 로 구분
}
CATALOG_ONLY_SOURCES = {"laftel"}           # + aniplus spa_page target

_matcher: NameMatcher | None = None
_matcher_loaded_at = 0.0
MATCHER_TTL_SEC = 600


async def get_matcher() -> NameMatcher:
    """backend 에서 이름 목록을 받아 10분 캐시. backend 가 안 되면 빈 매처 (매칭 없이 검수로)."""
    global _matcher, _matcher_loaded_at
    if _matcher is None or time.monotonic() - _matcher_loaded_at > MATCHER_TTL_SEC:
        try:
            rows = await get_backend().get_catalog_names()
            _matcher = NameMatcher([CatalogName(r["kind"], r["id"], r["name"]) for r in rows])
        except Exception:  # noqa: BLE001
            log.warning("catalog names load failed — empty matcher", exc_info=True)
            _matcher = _matcher or NameMatcher([])
        _matcher_loaded_at = time.monotonic()
    return _matcher


async def run_process_for_scrape_job(scrape_job_id: int) -> int:
    async with SessionLocal() as session:
        pjob = await job_repository.create_process_job(session, scrape_job_id=scrape_job_id)
        pjob.status = ProcessJobStatus.RUNNING
        pjob.started_at = now_kst()
        await session.commit()

        sjob = await job_repository.get_scrape_job(session, scrape_job_id)
        source = await source_repository.get(session, sjob.source_id)
        target = await target_repository.get(session, sjob.target_id) if sjob.target_id else None

        if source.name in CATALOG_ONLY_SOURCES or (target and target.target_type == TargetType.SPA_PAGE):
            from src.services.catalog_service import link_streaming
            raws = await raw_item_repository.list_for_job(session, scrape_job_id)
            result = await link_streaming(raws, await get_matcher())
            pjob.total_count = len(raws)
            pjob.processed_count = result.linked
            pjob.failed_count = result.failed
            pjob.error_message = result.message()   # 매칭 못 한 작품 목록 → 관리자가 별칭 추가
            pjob.status = ProcessJobStatus.COMPLETED
            pjob.finished_at = now_kst()
            await session.commit()
            return pjob.id

        parser = PARSERS.get(source.name)
        matcher = await get_matcher()
        raws = await raw_item_repository.list_for_job(session, scrape_job_id)
        pjob.total_count = len(raws)
        to_publish: list[int] = []

        for raw in raws:
            try:
                if parser is None:
                    raise NotImplementedError(f"no parser for {source.name}")
                parsed = parser.parse(raw, source_name=source.name)
                if parsed is None:
                    continue
                if target and (target.artist_id or target.anime_id):
                    # 대상 자체가 특정 아티스트/작품 계정이면 그게 정답
                    parsed.artist_id, parsed.anime_id = target.artist_id, target.anime_id
                else:
                    cand = matcher.best(parsed.keywords + [parsed.title])
                    if cand:
                        setattr(parsed, f"{cand.kind}_id", cand.id)
                        parsed.confidence = round(cand.score, 2)
                # SAVEPOINT: 한 건이 DB 제약(CHECK 등)에 걸려도 트랜잭션 전체가 aborted 되지 않게
                # (PostgreSQL 은 에러 난 트랜잭션에서 ROLLBACK 전까지 다음 쿼리를 전부 거부함)
                async with session.begin_nested():
                    item_id = await processed_item_repository.upsert_for_raw(
                        session, raw_item_id=raw.id, process_job_id=pjob.id, values=parsed.to_values()
                    )
                pjob.processed_count += 1
                # 자동 게시는 작품/아티스트가 매칭된 것만. 매칭 없으면 pending 으로 남겨 검수
                # (안 그러면 main 에 작품 없는 방영·공연 이벤트가 대량으로 생김)
                if source.auto_publish and (parsed.artist_id or parsed.anime_id):
                    to_publish.append(item_id)
            except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 막지 않게
                pjob.failed_count += 1
                await error_repository.record(session, job_type=ErrorJobType.PROCESS, job_id=pjob.id,
                                              error_type="parse_error", exc=exc, raw_item_id=raw.id)

        pjob.status = ProcessJobStatus.COMPLETED
        pjob.finished_at = now_kst()
        await session.commit()

    if to_publish:
        from src.services.publish_service import publish  # 순환 import 방지
        for item_id in to_publish:
            try:
                await publish(item_id, reviewed_by=None)
            except Exception:  # noqa: BLE001
                log.exception("auto publish failed for processed_item %s", item_id)
    return pjob.id

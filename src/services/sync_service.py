"""소스별 동기화 (api문서 /internal/{소스}/sync) → scrape_job 큐 등록.

- 공통 규칙 'sync 는 202': 여기서는 잡만 만들고, 실제 수집은 BackgroundTasks 가 collect_service 로 실행
- body 값(weeks, afterdate, season …)은 scrape_job.target 에 JSON 으로 실어 컬렉터의 params 로 전달
- 사이트가 바뀌어도 이 파일은 그대로 (소스 이름 → 컬렉터 매핑은 collectors/registry.py)
"""
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import TargetType
from src.repositories import job_repository, source_repository, target_repository

PARAMS_PREFIX = "params:"


class SourceNotFound(LookupError):
    pass


def encode_params(params: dict[str, Any] | None) -> str | None:
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    return PARAMS_PREFIX + json.dumps(clean, ensure_ascii=False) if clean else None


def decode_params(target: str | None) -> dict[str, Any]:
    if target and target.startswith(PARAMS_PREFIX):
        return json.loads(target[len(PARAMS_PREFIX):])
    return {}


async def enqueue_source(session: AsyncSession, source_name: str, *, target_type: TargetType | None = None,
                         params: dict[str, Any] | None = None) -> list[int]:
    """검증된 active 대상마다 잡 1개. 대상이 없는 소스(API 형) 또는 target_type 미지정이면 소스 전체 잡 1개."""
    source = await source_repository.get_by_name(session, source_name)
    if source is None:
        raise SourceNotFound(source_name)
    targets = await target_repository.list_collectable(session, source.id)
    if target_type is not None:
        targets = [t for t in targets if t.target_type == target_type]
    encoded = encode_params(params)
    job_ids: list[int] = []
    for t in targets or [None]:
        job = await job_repository.create_scrape_job(
            session, source_id=source.id, target_id=t.id if t else None,
            target=encoded or (t.value if t else None),
        )
        job_ids.append(job.id)
    return job_ids

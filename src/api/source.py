"""/internal/pipeline/sources — scrape_source CRUD (명주). 소스 켜기/끄기, config(delay_ms 등)."""
from fastapi import APIRouter, Query, status
from sqlalchemy.exc import IntegrityError

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.repositories import source_repository
from src.repositories.base import apply_patch
from src.schemas.common import ListResponse
from src.schemas.source import SourceCreate, SourceOut, SourceUpdate

router = APIRouter(prefix="/internal/pipeline/sources", tags=["pipeline:source"])


@router.get("", response_model=ListResponse[SourceOut])
async def list_sources(session: SessionDep, page: PageDep, enabled: bool | None = Query(None)):
    items, total = await source_repository.list_(session, page, enabled=enabled)
    return ListResponse(items=items, meta=meta(page, total))


@router.get("/{sourceId}", response_model=SourceOut)
async def get_source(sourceId: int, session: SessionDep):  # noqa: N803 — URL 변수 camelCase 규칙
    source = await source_repository.get(session, sourceId)
    if source is None:
        raise not_found("source")
    return source


@router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(body: SourceCreate, session: SessionDep):
    try:
        source = await source_repository.create(session, **body.model_dump())
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict("source name already exists") from exc
    return source


@router.patch("/{sourceId}", response_model=SourceOut)
async def update_source(sourceId: int, body: SourceUpdate, session: SessionDep):  # noqa: N803
    source = await source_repository.get(session, sourceId)
    if source is None:
        raise not_found("source")
    apply_patch(source, body.model_dump(exclude_unset=True))
    await session.commit()
    # TODO: enabled 바뀌면 이 소스의 스케줄 reload (scheduler.loader)
    return source

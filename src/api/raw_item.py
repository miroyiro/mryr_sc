"""/internal/pipeline/rawItems — raw_item 조회 (읽기 전용, 명주)."""
from fastapi import APIRouter, Query

from src.api.deps import PageDep, SessionDep, meta, not_found
from src.repositories import raw_item_repository
from src.schemas.common import ListResponse
from src.schemas.raw_item import RawItemOut

router = APIRouter(prefix="/internal/pipeline/rawItems", tags=["pipeline:raw"])


@router.get("", response_model=ListResponse[RawItemOut])
async def list_raw_items(
    session: SessionDep, page: PageDep,
    source_id: int | None = Query(None, alias="sourceId"),
    job_id: int | None = Query(None, alias="jobId"),
):
    items, total = await raw_item_repository.list_(session, page, source_id=source_id, scrape_job_id=job_id)
    return ListResponse(items=items, meta=meta(page, total))


@router.get("/{rawItemId}", response_model=RawItemOut)
async def get_raw_item(rawItemId: int, session: SessionDep):  # noqa: N803
    item = await raw_item_repository.get(session, rawItemId)
    if item is None:
        raise not_found("raw item")
    return item

"""/internal/pipeline/rawItems — api문서: GET 목록 · DELETE /{id}. 문서에 추가: GET /{id}."""
from fastapi import APIRouter, Query

from src.api.deps import PageDep, SessionDep, meta, not_found
from src.repositories import raw_item_repository
from src.schemas.common import DataResponse, DeletedOut, ListResponse
from src.schemas.raw_item import RawItemOut

router = APIRouter(prefix="/internal/pipeline/rawItems", tags=["pipeline:raw"])


@router.get("", response_model=ListResponse[RawItemOut])
async def list_raw_items(
    session: SessionDep, page: PageDep,
    source_id: int | None = Query(None, alias="sourceId"),
    job_id: int | None = Query(None, alias="jobId"),
):
    items, total = await raw_item_repository.list_(session, page, source_id=source_id, scrape_job_id=job_id)
    return ListResponse(data=items, meta=meta(page, total))


@router.get("/{id}", response_model=DataResponse[RawItemOut])
async def get_raw_item(id: int, session: SessionDep):  # noqa: A002
    item = await raw_item_repository.get(session, id)
    if item is None:
        raise not_found("raw item")
    return DataResponse(data=item)


@router.delete("/{id}", response_model=DataResponse[DeletedOut])
async def delete_raw_item(id: int, session: SessionDep):  # noqa: A002
    item = await raw_item_repository.get(session, id)
    if item is None:
        raise not_found("raw item")
    await raw_item_repository.delete(session, item)
    await session.commit()
    return DataResponse(data=DeletedOut(id=id))

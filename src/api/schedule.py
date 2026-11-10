"""/internal/pipeline/schedules — scrape_schedule CRUD (명주). 바뀌면 스케줄러에 바로 반영."""
from fastapi import APIRouter, Query, status

from src.api.deps import PageDep, SessionDep, meta, not_found
from src.repositories import schedule_repository, source_repository
from src.repositories.base import apply_patch
from src.scheduler import loader
from src.schemas.common import DataResponse, DeletedOut, ListResponse
from src.schemas.schedule import ScheduleCreate, ScheduleOut, ScheduleUpdate

router = APIRouter(prefix="/internal/pipeline/schedules", tags=["pipeline:schedule"])


@router.get("", response_model=ListResponse[ScheduleOut])
async def list_schedules(session: SessionDep, page: PageDep, source_id: int | None = Query(None, alias="sourceId")):
    items, total = await schedule_repository.list_(session, page, source_id=source_id)
    return ListResponse(data=items, meta=meta(page, total))


@router.post("", response_model=DataResponse[ScheduleOut], status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleCreate, session: SessionDep):
    if await source_repository.get(session, body.source_id) is None:
        raise not_found("source")
    schedule = await schedule_repository.create(session, **body.model_dump())
    await session.commit()
    await loader.reload_one(schedule.id)
    return DataResponse(data=schedule)


@router.patch("/{id}", response_model=DataResponse[ScheduleOut])
async def update_schedule(id: int, body: ScheduleUpdate, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    schedule = await schedule_repository.get(session, id)
    if schedule is None:
        raise not_found("schedule")
    apply_patch(schedule, body.model_dump(exclude_unset=True))
    await session.commit()  # ck_schedule_shape 위반이면 IntegrityError → 400 핸들러 (main.py)
    await loader.reload_one(id)
    return DataResponse(data=schedule)


@router.delete("/{id}", response_model=DataResponse[DeletedOut])
async def delete_schedule(id: int, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    schedule = await schedule_repository.get(session, id)
    if schedule is None:
        raise not_found("schedule")
    await schedule_repository.delete(session, schedule)
    await session.commit()
    loader.unregister(id)
    return DataResponse(data=DeletedOut(id=id))

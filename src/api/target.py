"""/internal/pipeline/targets — scrape_target CRUD (명주). is_verified 는 /verify 로만."""
from fastapi import APIRouter, Query, status
from sqlalchemy.exc import IntegrityError

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.models.enums import TargetStatus
from src.repositories import source_repository, target_repository
from src.repositories.base import apply_patch
from src.schemas.common import DataResponse, DeletedOut, ListResponse
from src.schemas.target import TargetCreate, TargetOut, TargetUpdate, TargetVerify

router = APIRouter(prefix="/internal/pipeline/targets", tags=["pipeline:target"])


@router.get("", response_model=ListResponse[TargetOut])
async def list_targets(
    session: SessionDep, page: PageDep,
    source_id: int | None = Query(None, alias="sourceId"),
    verified: bool | None = Query(None),
    status_: TargetStatus | None = Query(None, alias="status"),
):
    items, total = await target_repository.list_(session, page, source_id=source_id, verified=verified, status=status_)
    return ListResponse(data=items, meta=meta(page, total))


@router.get("/{id}", response_model=DataResponse[TargetOut])
async def get_target(id: int, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    target = await target_repository.get(session, id)
    if target is None:
        raise not_found("target")
    return DataResponse(data=target)


@router.post("", response_model=DataResponse[TargetOut], status_code=status.HTTP_201_CREATED)
async def create_target(body: TargetCreate, session: SessionDep):
    if await source_repository.get(session, body.source_id) is None:
        raise not_found("source")
    try:
        target = await target_repository.create(session, **body.model_dump())
        await session.commit()
    except IntegrityError as exc:  # uq_target(source_id, value) 또는 ck_target_type
        await session.rollback()
        raise conflict("target already exists for this source") from exc
    return DataResponse(data=target)


@router.patch("/{id}", response_model=DataResponse[TargetOut])
async def update_target(id: int, body: TargetUpdate, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    target = await target_repository.get(session, id)
    if target is None:
        raise not_found("target")
    apply_patch(target, body.model_dump(exclude_unset=True))
    await session.commit()
    await session.refresh(target)  # updated_at (DB 트리거) 다시 읽기
    return DataResponse(data=target)


@router.post("/{id}/verify", response_model=DataResponse[TargetOut])
async def verify_target(id: int, body: TargetVerify, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    """관리자 검증. 검증 안 된 대상은 스케줄러가 수집하지 않음 (04: is_verified 대상만)."""
    target = await target_repository.get(session, id)
    if target is None:
        raise not_found("target")
    target.is_verified = body.is_verified
    # TODO: 감사 로그가 필요하면 verified_by/at 컬럼 추가 (지금 ERD엔 없음)
    await session.commit()
    return DataResponse(data=target)


@router.delete("/{id}", response_model=DataResponse[DeletedOut])
async def delete_target(id: int, session: SessionDep):  # noqa: A002 — 문서 경로 변수 {id}
    target = await target_repository.get(session, id)
    if target is None:
        raise not_found("target")
    await target_repository.delete(session, target)
    await session.commit()
    return DataResponse(data=DeletedOut(id=id))

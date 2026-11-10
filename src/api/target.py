"""/internal/pipeline/targets — scrape_target CRUD (명주). is_verified 는 /verify 로만."""
from fastapi import APIRouter, Query, Response, status
from sqlalchemy.exc import IntegrityError

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.models.enums import TargetStatus
from src.repositories import source_repository, target_repository
from src.repositories.base import apply_patch
from src.schemas.common import ListResponse
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
    return ListResponse(items=items, meta=meta(page, total))


@router.get("/{targetId}", response_model=TargetOut)
async def get_target(targetId: int, session: SessionDep):  # noqa: N803
    target = await target_repository.get(session, targetId)
    if target is None:
        raise not_found("target")
    return target


@router.post("", response_model=TargetOut, status_code=status.HTTP_201_CREATED)
async def create_target(body: TargetCreate, session: SessionDep):
    if await source_repository.get(session, body.source_id) is None:
        raise not_found("source")
    try:
        target = await target_repository.create(session, **body.model_dump())
        await session.commit()
    except IntegrityError as exc:  # uq_target(source_id, value) 또는 ck_target_type
        await session.rollback()
        raise conflict("target already exists for this source") from exc
    return target


@router.patch("/{targetId}", response_model=TargetOut)
async def update_target(targetId: int, body: TargetUpdate, session: SessionDep):  # noqa: N803
    target = await target_repository.get(session, targetId)
    if target is None:
        raise not_found("target")
    apply_patch(target, body.model_dump(exclude_unset=True))
    await session.commit()
    return target


@router.post("/{targetId}/verify", response_model=TargetOut)
async def verify_target(targetId: int, body: TargetVerify, session: SessionDep):  # noqa: N803
    """관리자 검증. 검증 안 된 대상은 스케줄러가 수집하지 않음 (04: is_verified 대상만)."""
    target = await target_repository.get(session, targetId)
    if target is None:
        raise not_found("target")
    target.is_verified = body.is_verified
    # TODO: 감사 로그가 필요하면 verified_by/at 컬럼 추가 (지금 ERD엔 없음)
    await session.commit()
    return target


@router.delete("/{targetId}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(targetId: int, session: SessionDep):  # noqa: N803
    target = await target_repository.get(session, targetId)
    if target is None:
        raise not_found("target")
    await target_repository.delete(session, target)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

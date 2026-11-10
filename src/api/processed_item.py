"""검수 · 가공 데이터 · 팝업 후보 큐 — api문서 '파이프라인' 기준.

backend 관리자 API 가 Tailscale 너머로 부른다 (관리자 토큰·role 403 검사는 backend 몫).
  GET    /internal/pipeline/review                 검수 대기 목록 (?status=pending 기본)
  PATCH  /internal/pipeline/review/{id}/approve    승인 → main 반영 (멱등)
  PATCH  /internal/pipeline/review/{id}/reject     반려
  GET|PATCH|DELETE /internal/pipeline/processedItems/{id}
  GET    /internal/events/candidates               팝업 후보 큐 (popup·collabo_cafe·fair)
"""
from fastapi import APIRouter, HTTPException, Query, status

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.clients.backend_client import BackendError
from src.models.enums import ProcessedCategory, ProcessedStatus
from src.repositories import processed_item_repository
from src.repositories.base import apply_patch
from src.schemas.common import DataResponse, DeletedOut, ListResponse
from src.schemas.processed_item import (
    ApproveOut, ApproveRequest, CandidateOut, ProcessedItemOut, ProcessedItemUpdate, RejectOut, RejectRequest,
    ReviewItemOut,
)
from src.services import publish_service

review_router = APIRouter(prefix="/internal/pipeline/review", tags=["pipeline:review"])
router = APIRouter(prefix="/internal/pipeline/processedItems", tags=["pipeline:processed"])
candidates_router = APIRouter(prefix="/internal/events/candidates", tags=["pipeline:candidates"])


# ---------------------------------------------------------------- review
@review_router.get("", response_model=ListResponse[ReviewItemOut])
async def list_review(
    session: SessionDep, page: PageDep,
    status_: ProcessedStatus | None = Query(ProcessedStatus.PENDING, alias="status"),
    category: ProcessedCategory | None = Query(None),
):
    rows, total = await processed_item_repository.list_review(session, page, status=status_, category=category)
    data = [
        ReviewItemOut(id=i.id, artist_id=i.artist_id, anime_id=i.anime_id, title=i.title, category=i.category,
                      status=i.status, confidence=i.confidence, source_url=url, created_at=i.created_at)
        for i, url in rows
    ]
    return ListResponse(data=data, meta=meta(page, total))


@review_router.patch("/{id}/approve", response_model=DataResponse[ApproveOut])
async def approve(id: int, body: ApproveRequest):  # noqa: A002
    try:
        item = await publish_service.publish(id, reviewed_by=body.reviewer_id)
    except LookupError as exc:
        raise not_found("processed item") from exc
    except publish_service.PublishConflict as exc:
        raise conflict(str(exc)) from exc
    except publish_service.PublishInvalid as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except BackendError as exc:  # backend 가 이상한 응답 → 502
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "backend error") from exc
    return DataResponse(data=ApproveOut(id=item.id, status=item.status, published_event_id=item.published_event_id,
                                        published_news_id=item.published_news_id, reviewed_at=item.reviewed_at))


@review_router.patch("/{id}/reject", response_model=DataResponse[RejectOut])
async def reject(id: int, body: RejectRequest):  # noqa: A002
    try:
        await publish_service.reject(id, reviewed_by=body.reviewer_id, reason=body.reason)
    except LookupError as exc:
        raise not_found("processed item") from exc
    except publish_service.PublishConflict as exc:
        raise conflict(str(exc)) from exc
    return DataResponse(data=RejectOut(id=id, status=ProcessedStatus.REJECTED, reason=body.reason))


# ---------------------------------------------------------------- processedItems/{id}
@router.get("/{id}", response_model=DataResponse[ProcessedItemOut])
async def get_processed(id: int, session: SessionDep):  # noqa: A002
    item = await processed_item_repository.get(session, id)
    if item is None:
        raise not_found("processed item")
    return DataResponse(data=item)


@router.patch("/{id}", response_model=DataResponse[ProcessedItemOut])
async def update_processed(id: int, body: ProcessedItemUpdate, session: SessionDep):  # noqa: A002
    item = await processed_item_repository.get(session, id, for_update=True)
    if item is None:
        raise not_found("processed item")
    if item.status != ProcessedStatus.PENDING:
        raise conflict("pending 상태만 수정할 수 있음")
    apply_patch(item, body.model_dump(exclude_unset=True))
    await session.commit()
    await session.refresh(item)  # updated_at (트리거) 다시 읽기
    return DataResponse(data=item)


@router.delete("/{id}", response_model=DataResponse[DeletedOut])
async def delete_processed(id: int, session: SessionDep):  # noqa: A002
    item = await processed_item_repository.get(session, id)
    if item is None:
        raise not_found("processed item")
    await processed_item_repository.delete(session, item)
    await session.commit()
    return DataResponse(data=DeletedOut(id=id))


# ---------------------------------------------------------------- candidates
@candidates_router.get("", response_model=ListResponse[CandidateOut])
async def list_candidates(
    session: SessionDep, page: PageDep,
    status_: ProcessedStatus | None = Query(None, alias="status"),
):
    rows, total = await processed_item_repository.list_candidates(session, page, status=status_)
    data = [
        CandidateOut(candidate_id=i.id, category=i.category, source=src_name, account=raw.author, url=raw.url,
                     keywords=i.keywords, published_at=raw.published_at, status=i.status)
        for i, raw, src_name in rows
    ]
    return ListResponse(data=data, meta=meta(page, total))

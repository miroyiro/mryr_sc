"""/internal/pipeline/processedItems — 검수 대기열 + 팝업 후보 큐 (명주).

backend admin API 가 Tailscale 너머로 이걸 부른다 (관리자 JWT 검사는 backend 몫).
  GET   ?status=pending&category=popup   → 팝업 후보 큐
  PATCH /{itemId}                         → 승인 전 보정 (매칭 대상, 날짜 등)
  POST  /{itemId}/approve                 → main 반영 (멱등)
  POST  /{itemId}/reject
"""
from fastapi import APIRouter, HTTPException, Query, status

from src.api.deps import PageDep, SessionDep, conflict, meta, not_found
from src.clients.backend_client import BackendError
from src.models.enums import ProcessedCategory, ProcessedStatus
from src.repositories import processed_item_repository
from src.repositories.base import apply_patch
from src.schemas.common import ListResponse
from src.schemas.processed_item import (
    ApproveRequest, ProcessedItemOut, ProcessedItemUpdate, PublishResult, RejectRequest,
)
from src.services import publish_service

router = APIRouter(prefix="/internal/pipeline/processedItems", tags=["pipeline:processed"])


@router.get("", response_model=ListResponse[ProcessedItemOut])
async def list_processed(
    session: SessionDep, page: PageDep,
    status_: ProcessedStatus | None = Query(ProcessedStatus.PENDING, alias="status"),
    category: ProcessedCategory | None = Query(None),
):
    items, total = await processed_item_repository.list_(session, page, status=status_, category=category)
    return ListResponse(items=items, meta=meta(page, total))


@router.get("/{itemId}", response_model=ProcessedItemOut)
async def get_processed(itemId: int, session: SessionDep):  # noqa: N803
    item = await processed_item_repository.get(session, itemId)
    if item is None:
        raise not_found("processed item")
    return item


@router.patch("/{itemId}", response_model=ProcessedItemOut)
async def update_processed(itemId: int, body: ProcessedItemUpdate, session: SessionDep):  # noqa: N803
    item = await processed_item_repository.get(session, itemId, for_update=True)
    if item is None:
        raise not_found("processed item")
    if item.status != ProcessedStatus.PENDING:
        raise conflict("only pending items can be edited")
    apply_patch(item, body.model_dump(exclude_unset=True))
    await session.commit()
    return item


@router.post("/{itemId}/approve", response_model=PublishResult)
async def approve(itemId: int, body: ApproveRequest):  # noqa: N803
    try:
        item = await publish_service.publish(itemId, reviewed_by=body.reviewed_by)
    except LookupError as exc:
        raise not_found("processed item") from exc
    except publish_service.PublishConflict as exc:
        raise conflict(str(exc)) from exc
    except publish_service.PublishInvalid as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except BackendError as exc:  # backend 가 이상한 응답 → 502 (06 규칙)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "backend error") from exc
    return PublishResult(id=item.id, status=item.status, published_event_id=item.published_event_id,
                         published_news_id=item.published_news_id)


@router.post("/{itemId}/reject", response_model=ProcessedItemOut)
async def reject(itemId: int, body: RejectRequest, session: SessionDep):  # noqa: N803
    try:
        await publish_service.reject(itemId, reviewed_by=body.reviewed_by, reason=body.reject_reason)
    except LookupError as exc:
        raise not_found("processed item") from exc
    except publish_service.PublishConflict as exc:
        raise conflict(str(exc)) from exc
    return await processed_item_repository.get(session, itemId)

"""승인/반려 → main 반영 (명주).

관리자 경로: 브라우저 → backend /api/admin/pipeline/... (JWT + admin 403)
           → (Tailscale) → scrap /internal/pipeline/processedItems/{itemId}/approve (X-Internal-Key)
           → scrap 이 backend /internal/pipeline/events|news 호출 (processed_item_id 멱등키)

순서가 중요:
  1) processed_item 을 FOR UPDATE 로 잠그고 pending 인지 확인 (동시 승인 방지)
  2) backend 호출 (외부 → 실패하면 아무것도 안 바뀐 상태로 끝)
  3) 성공하면 published 로 표시 + id 저장 → commit
  2와 3 사이에 죽으면? backend 에는 행이 있고 scrap 은 pending → 다시 승인하면 멱등키 덕분에 같은 id 를 받음
"""
from src.clients.backend_client import BackendError, get_backend
from src.config.database import SessionLocal
from src.models.enums import NEWS_SOURCES, MainSource, ProcessedCategory, ProcessedStatus
from src.repositories import processed_item_repository, raw_item_repository, source_repository


class PublishConflict(Exception):
    """이미 published/rejected → 라우터에서 409."""


class PublishInvalid(Exception):
    """event_data 없음 등 승인할 수 없는 상태 → 라우터에서 400."""


async def publish(item_id: int, *, reviewed_by: int | None):
    async with SessionLocal() as session:
        item = await processed_item_repository.get(session, item_id, for_update=True)
        if item is None:
            raise LookupError(item_id)
        if item.status != ProcessedStatus.PENDING:
            raise PublishConflict(f"processed_item {item_id} is {item.status}")

        raw = await raw_item_repository.get(session, item.raw_item_id)
        source = await source_repository.get(session, raw.source_id)
        backend = get_backend()
        event_id = news_id = None

        try:
            if ProcessedCategory(item.category).is_event:
                if not item.event_data or not item.event_data.get("start_at"):
                    raise PublishInvalid("event_data.start_at 없음 — 검수 화면에서 날짜를 채워야 승인 가능")
                event_data = {**item.event_data, "artist_id": item.artist_id, "anime_id": item.anime_id}
                event_id = await backend.publish_event(processed_item_id=item.id, event_data=event_data)
            else:
                if MainSource(source.name) not in NEWS_SOURCES:
                    raise PublishInvalid(f"news_feed.source 에 {source.name} 불가 (ck_news_source)")
                news_id = await backend.publish_news(processed_item_id=item.id, news={
                    "category": "jpop" if item.artist_id else "anime",
                    "artist_id": item.artist_id,
                    "anime_id": item.anime_id,
                    "source": source.name,
                    "source_url": raw.url,
                    "title": item.title,
                    "summary": item.summary,
                    "published_at": raw.published_at.isoformat() if raw.published_at else None,
                })
        except BackendError as exc:
            await session.rollback()
            if exc.status == 400:
                raise PublishInvalid(str(exc)) from exc
            raise

        await processed_item_repository.mark_published(
            session, item, reviewed_by=reviewed_by, event_id=event_id, news_id=news_id
        )
        await session.commit()
        return item


async def reject(item_id: int, *, reviewed_by: int, reason: str) -> None:
    async with SessionLocal() as session:
        if not await processed_item_repository.mark_rejected(session, item_id, reviewed_by=reviewed_by, reason=reason):
            item = await processed_item_repository.get(session, item_id)
            if item is None:
                raise LookupError(item_id)
            raise PublishConflict(f"processed_item {item_id} is {item.status}")
        await session.commit()

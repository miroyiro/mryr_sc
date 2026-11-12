"""scrap → backend(Spring) 내부 API 클라이언트 (명주 안 — 03 문서엔 담당 미배정).

네트워크: 미니PC → (Tailscale) → AWS EC2 backend  /internal/**
인증: X-Internal-Key = settings.BACKEND_INTERNAL_KEY (backend→scrap 키와 다른 값)
멱등성: 모든 게시 요청에 processed_item_id 를 같이 보냄 → backend는 UNIQUE(processed_item_id)로
        같은 요청이 두 번 와도 행 1개. 이미 있으면 200 + 기존 id 돌려주기로 backend와 합의.

backend 쪽 엔드포인트 (Spring internal 패키지에 만들 것 — 03 문서 참고)
  POST /internal/pipeline/events     body = event_data + processed_item_id   → {"id": n}
  POST /internal/pipeline/news       body = news payload + processed_item_id → {"id": n}
  POST /internal/catalog/anime       AniList/애니시아/TMDB 결과 upsert       → {"id": n}
  POST /internal/catalog/streaming   anime_streaming upsert (laftel·aniplus) → {"count": n}
  GET  /internal/catalog/names?since= name_matcher 용 이름 목록             → {"items": [...]}
"""
import asyncio
import logging
from typing import Any

import httpx

from src.config.settings import settings

log = logging.getLogger(__name__)


class BackendError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"backend {status}: {body[:200]}")
        self.status = status


class BackendClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=settings.BACKEND_INTERNAL_URL,
            headers={"X-Internal-Key": settings.BACKEND_INTERNAL_KEY.get_secret_value()},
            timeout=settings.BACKEND_TIMEOUT_SEC,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------- pipeline
    async def publish_event(self, *, processed_item_id: int, event_data: dict[str, Any]) -> int:
        body = {**event_data, "processed_item_id": processed_item_id}
        return (await self._post("/internal/pipeline/events", body))["id"]

    async def publish_news(self, *, processed_item_id: int, news: dict[str, Any]) -> int:
        body = {**news, "processed_item_id": processed_item_id}
        return (await self._post("/internal/pipeline/news", body))["id"]

    # ---------------------------------------------------------- catalog
    async def upsert_anime(self, payload: dict[str, Any]) -> int:
        return (await self._post("/internal/catalog/anime", payload))["id"]

    async def upsert_streaming(self, *, anime_id: int, links: list[dict[str, Any]]) -> int:
        return (await self._post("/internal/catalog/streaming", {"anime_id": anime_id, "links": links}))["count"]

    async def get_catalog_names(self, since: str | None = None) -> list[dict[str, Any]]:
        params = {"since": since} if since else None
        return (await self._request("GET", "/internal/catalog/names", params=params))["items"]

    # ---------------------------------------------------------- core
    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json=body)

    async def _request(self, method: str, path: str, **kw) -> dict[str, Any]:
        """연결 오류·5xx 만 재시도 (멱등키가 있으니 POST 재시도도 안전). 4xx 는 바로 실패."""
        last: Exception | None = None
        for attempt in range(1, 4):
            try:
                resp = await self._client.request(method, path, **kw)
            except httpx.TransportError as exc:   # Tailscale 끊김, backend 재시작 등
                last = exc
            else:
                if resp.status_code < 400:
                    return resp.json()
                if resp.status_code < 500:
                    raise BackendError(resp.status_code, resp.text)
                last = BackendError(resp.status_code, resp.text)
            await asyncio.sleep(2 ** attempt)
            log.warning("backend %s %s retry %s: %s", method, path, attempt, last)
        assert last is not None
        raise last


_backend: BackendClient | None = None


def get_backend() -> BackendClient:
    global _backend
    if _backend is None:
        _backend = BackendClient()
    return _backend


async def close_backend() -> None:
    global _backend
    if _backend is not None:
        await _backend.aclose()
        _backend = None

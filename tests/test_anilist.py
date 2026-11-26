"""AniList 클라이언트 (httpx MockTransport — 네트워크·DB 없음).

실응답 픽스처가 없음 → 응답 body 는 필요한 키만 넣은 최소 모양 (필드명 미검증).
"""
import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import resolve as resolve_api
from src.collectors.api import anilist
from src.collectors.api.anilist import AniListCollector, AniListError, AniListRateLimited
from src.config.settings import settings
from src.services import anilist_resolver


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(anilist, "_sleep", no_sleep)
    monkeypatch.setattr(settings, "HTTP_MAX_RETRIES", 3)


def _run(responses, call):
    """responses 를 순서대로 돌려주는 MockTransport 로 call(collector) 실행 → (결과, 요청 목록)."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(req):
        seen.append(req)
        return queue.pop(0)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await call(AniListCollector(client=client))

    return asyncio.run(run()), seen


def _ok(data):
    return httpx.Response(200, json={"data": data})


SEASON_OK = {"Page": {"pageInfo": {"hasNextPage": False}, "media": [{"id": 1, "status": "RELEASING"}]}}


def test_retry_on_429_then_ok():
    out, seen = _run([httpx.Response(429, headers={"Retry-After": "1"}), _ok({"x": 1})],
                     lambda c: c.request("query{}"))
    assert out == ({"x": 1}, None) and len(seen) == 2


def test_retry_on_503_then_ok():
    out, seen = _run([httpx.Response(503), _ok({"x": 1})], lambda c: c.request("query{}"))
    assert out[0] == {"x": 1} and len(seen) == 2


def test_429_exhausted_raises_rate_limited():
    with pytest.raises(AniListRateLimited) as ei:
        _run([httpx.Response(429, headers={"Retry-After": "42"})] * 3, lambda c: c.request("query{}"))
    assert ei.value.retry_after == 42


def test_429_without_retry_after_defaults_60():
    with pytest.raises(AniListRateLimited) as ei:
        _run([httpx.Response(429)] * 3, lambda c: c.request("query{}"))
    assert ei.value.retry_after == 60


def test_4xx_no_retry():
    seen: list = []

    def handler(req):
        seen.append(req)
        return httpx.Response(400, json={"errors": [{"message": "bad"}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await AniListCollector(client=client).request("query{}")

    with pytest.raises(AniListError) as ei:
        asyncio.run(run())
    assert ei.value.status == 400 and len(seen) == 1


@pytest.mark.parametrize("resp", [
    httpx.Response(200, json={}),
    httpx.Response(200, json={"data": None}),
    httpx.Response(200, text="<html>maintenance</html>"),
])
def test_missing_data_raises(resp):
    with pytest.raises(AniListError):
        _run([resp], lambda c: c.request("query{}"))


def test_search_empty_and_missing_id():
    out, seen = _run([_ok({"Page": {"media": []}})], lambda c: c.search_media("없는 제목"))
    assert out == []
    out, _ = _run([_ok({"Page": {"media": [{"id": 5, "title": {"romaji": "A"}}, {"title": {"romaji": "no id"}}]}})],
                  lambda c: c.search_media("A"))
    assert [m["id"] for m in out] == [5]
    with pytest.raises(AniListError):        # Page 자체가 없으면 형식 변경 → 실패
        _run([_ok({})], lambda c: c.search_media("A"))


def test_search_sends_variables():
    _, seen = _run([_ok({"Page": {"media": []}})], lambda c: c.search_media("바람의 저편", per_page=3))
    import json
    body = json.loads(seen[0].content)
    assert body["variables"] == {"search": "바람의 저편", "perPage": 3}


def test_fetch_media_batch_null_alias_and_chunks():
    ids = list(range(1, 13))                  # 12개 → 10 + 2 로 2번
    first = {f"m{i}": {"id": ids[i]} for i in range(10)}
    first["m3"] = None                        # 없는 id 는 null alias 라고 가정 (실제 응답 미검증)
    second = {"m0": {"id": 11}, "m1": {"id": 12, "format": "TV"}}
    out, seen = _run([_ok(first), _ok(second)], lambda c: c.fetch_media_batch(ids))
    assert len(seen) == 2
    assert sorted(out) == [i for i in ids if i != 4]
    assert out[12]["format"] == "TV"          # 원본 media 그대로


def test_fetch_media_batch_empty():
    out, seen = _run([], lambda c: c.fetch_media_batch([]))
    assert out == {} and seen == []


def test_fetch_season_ids_key():
    out, _ = _run([_ok(SEASON_OK)], lambda c: c.fetch_season_ids("fall", 2026))
    assert out == [{"id": 1, "status": "RELEASING"}]


def test_aclose_own_vs_injected():
    async def run():
        own = AniListCollector()
        await own.aclose()
        injected = httpx.AsyncClient()
        await AniListCollector(client=injected).aclose()
        closed = injected.is_closed
        await injected.aclose()
        return own.client.is_closed, closed

    assert asyncio.run(run()) == (True, False)


def test_resolver_closes_on_error(monkeypatch):
    closed = []

    class FakeApi:
        async def fetch_season_ids(self, season, year):
            raise AniListRateLimited(30)

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(anilist_resolver, "_get_api", lambda: FakeApi())
    with pytest.raises(AniListRateLimited):
        asyncio.run(anilist_resolver.sync_season("fall", 2026))
    assert closed == [True]


def test_resolve_endpoint_429_to_503(monkeypatch):
    async def limited(titles):
        raise AniListRateLimited(42)

    monkeypatch.setattr(anilist_resolver, "resolve_titles", limited)
    app = FastAPI()
    app.include_router(resolve_api.router)
    r = TestClient(app).post("/internal/anilist/resolve", json={"titles": ["바람의 저편"]})
    assert r.status_code == 503 and r.headers["Retry-After"] == "42"

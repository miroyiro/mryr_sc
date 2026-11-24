"""API 컬렉터 규약 (kopis·anissia). 네트워크 없음: httpx.MockTransport 로 응답을 흉내낸다."""
import asyncio
import traceback
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from src.collectors import base_api_collector
from src.collectors.api.anissia import AnissiaCollector
from src.collectors.api.kopis import KopisCollector
from src.collectors.base_api_collector import ApiError
from src.collectors.registry import build_collector
from src.config.settings import settings

SECRET = "TEST-KOPIS-KEY-123"


def _source(name: str):
    # 게이트가 소스 이름별로 공유되므로 테스트마다 다른 이름 + 간격 0
    return SimpleNamespace(name=name, base_url=None, cfg=lambda k, d=None: {"delay_ms": 0}.get(k, d))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _no_sleep(_):
        return None
    monkeypatch.setattr(base_api_collector, "_sleep", _no_sleep)


@pytest.fixture
def kopis_key(monkeypatch):
    monkeypatch.setattr(settings, "KOPIS_API_KEY", SecretStr(SECRET))


def _run(collector_cls, name, handler, call):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await call(collector_cls(_source(name), client=client))
    return asyncio.run(run())


@pytest.mark.parametrize("name, cls", [("kopis", KopisCollector), ("anissia", AnissiaCollector)])
def test_registry_contract(name, cls):
    """registry 가 cls(source) 로 만들 수 있고, aclose 가 있다."""
    collector = build_collector(_source(name), None)
    assert isinstance(collector, cls)
    asyncio.run(collector.aclose())


def test_retry_5xx_then_ok():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json=[])

    items = _run(AnissiaCollector, "anissia-t1", handler, lambda c: c.fetch_week(1))
    assert items == []
    assert len(calls) == 2


def test_4xx_no_retry():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(404)

    with pytest.raises(ApiError) as ei:
        _run(AnissiaCollector, "anissia-t2", handler, lambda c: c.fetch_week(1))
    assert ei.value.status == 404
    assert len(calls) == 1


@pytest.mark.parametrize("status", [404, 500])
def test_kopis_key_not_in_error(kopis_key, status):
    """scrape_error 에는 repr(exc) + traceback 이 저장됨 → 둘 다에 키가 없어야 함."""
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(status)

    with pytest.raises(ApiError) as ei:
        _run(KopisCollector, f"kopis-t{status}", handler, lambda c: c.fetch_detail("PF000001"))
    assert SECRET in seen[0]                       # 실제 요청에는 키가 들어감
    stored = repr(ei.value) + "".join(traceback.format_exception(ei.value))
    assert SECRET not in stored
    assert "/pblprfr/PF000001" in str(ei.value)    # 어디서 실패했는지는 남김


def test_kopis_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "KOPIS_API_KEY", None)
    with pytest.raises(ApiError, match="KOPIS_API_KEY not set"):
        _run(KopisCollector, "kopis-t-nokey", lambda req: httpx.Response(200), lambda c: c.fetch_detail("PF1"))

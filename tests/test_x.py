"""X 컬렉터. 네트워크 없음: httpx.MockTransport.

픽스처 x_user_tweets.json 은 실제 응답이 아니라 공식 문서 형태를 보고 손으로 만든 가짜 데이터 (응답 형식 미검증).
"""
import asyncio
import json
import traceback
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from src.collectors import base_api_collector
from src.collectors.api.x import XBudgetNotSet, XCollector
from src.collectors.base_api_collector import ApiError
from src.collectors.registry import build_collector
from src.collectors.scraping.base_scraper import LayoutChanged
from src.config.settings import settings

FAKE_TOKEN = "fake-x-bearer-0000"
BUDGET = {"monthly_budget_usd": 30}

_seq = iter(range(10**6))


def _source(**cfg):
    conf = {"delay_ms": 0, **cfg}
    return SimpleNamespace(name=f"x-t{next(_seq)}", base_url=None, cfg=lambda k, d=None: conf.get(k, d))


def _account(**kw):
    base = dict(target_type="x_account", value="test_official", x_user_id="111", is_verified=True,
                last_seen_external_id=None, anime_id=None)
    return SimpleNamespace(**{**base, **kw})


def _keyword(**kw):
    base = dict(target_type="keyword", value="ポップアップ OR 팝업", x_user_id=None, is_verified=True,
                last_seen_external_id=None, anime_id=None)
    return SimpleNamespace(**{**base, **kw})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _no_sleep(_):
        return None
    monkeypatch.setattr(base_api_collector, "_sleep", _no_sleep)


@pytest.fixture(autouse=True)
def x_token(monkeypatch):
    monkeypatch.setattr(settings, "X_BEARER_TOKEN", SecretStr(FAKE_TOKEN))


@pytest.fixture
def tweets_json(fixture_text):
    return json.loads(fixture_text("x_user_tweets.json"))


def _run(handler, target, params=None, **cfg):
    seen: list[httpx.Request] = []

    def wrapped(req):
        seen.append(req)
        return handler(req)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as client:
            c = XCollector(_source(**cfg), client=client)
            try:
                return await c.collect(target, params)
            except Exception as exc:   # noqa: BLE001
                return exc
    return asyncio.run(run()), seen


def test_registry_contract():
    c = build_collector(SimpleNamespace(name="x", base_url=None, cfg=lambda k, d=None: d), None)
    assert isinstance(c, XCollector)
    asyncio.run(c.aclose())


# ---------- 차단 (요청 0건) ----------
def test_no_budget_blocks_before_any_request(tweets_json):
    out, seen = _run(lambda req: httpx.Response(200, json=tweets_json), _account())
    assert isinstance(out, XBudgetNotSet) and seen == []


def test_x_account_without_user_id_rejected(tweets_json):
    out, seen = _run(lambda req: httpx.Response(200, json=tweets_json), _account(x_user_id=None), **BUDGET)
    assert isinstance(out, ValueError) and seen == []


def test_unverified_target_rejected(tweets_json):
    out, seen = _run(lambda req: httpx.Response(200, json=tweets_json), _account(is_verified=False), **BUDGET)
    assert isinstance(out, ValueError) and seen == []


def test_target_none_rejected():
    out, seen = _run(lambda req: httpx.Response(200, json={}), None, **BUDGET)
    assert isinstance(out, ValueError) and seen == []


@pytest.mark.parametrize("value", [None, SecretStr("")])
def test_missing_token_raises_before_request(monkeypatch, value):
    monkeypatch.setattr(settings, "X_BEARER_TOKEN", value)
    out, seen = _run(lambda req: httpx.Response(200, json={}), _account(), **BUDGET)
    assert isinstance(out, RuntimeError) and seen == []
    assert str(out) == "X_BEARER_TOKEN not set"         # 무엇이 빠졌는지 이름이 보이는 에러


# ---------- 정상 흐름 ----------
def test_account_request_and_items(tweets_json):
    out, seen = _run(lambda req: httpx.Response(200, json=tweets_json),
                     _account(last_seen_external_id="1850000000000000000"), **BUDGET)
    [req] = seen
    assert req.url.path == "/2/users/111/tweets"
    p = req.url.params
    assert p["exclude"] == "retweets,replies" and p["since_id"] == "1850000000000000000"
    assert p["max_results"] == "20" and "note_tweet" in p["tweet.fields"]
    assert req.headers["authorization"] == f"Bearer {FAKE_TOKEN}"

    assert out.last_seen_external_id == "1860000000000000002"
    first, second = out.items
    assert first.external_id == "1860000000000000002"
    assert first.url == "https://x.com/test_official/status/1860000000000000002"
    assert first.content == tweets_json["data"][0]["text"]          # 원문 그대로
    assert first.title == "【告知】ポップアップストア開催決定！"
    assert first.published_at == datetime(2026, 11, 20, 3, tzinfo=timezone.utc)
    assert first.images is None                                    # 기본은 미디어 저장 X
    rd = first.raw_data
    assert rd["urls"] == ["https://example.com/popup"] and rd["media_types"] == ["photo", "video"]
    assert rd["referenced"] == [{"type": "quoted", "id": "1850000000000000000"}]
    assert second.content == "長い本文 全文\n二行目" and second.title == "長い本文 全文"   # note_tweet 우선


def test_store_media_keeps_only_photos(tweets_json):
    out, _ = _run(lambda req: httpx.Response(200, json=tweets_json), _account(), store_media=True, **BUDGET)
    assert out.items[0].images == ["https://pbs.twimg.com/media/a.jpg"]


def test_keyword_query_and_min_max_results(tweets_json):
    out, seen = _run(lambda req: httpx.Response(200, json=tweets_json), _keyword(last_seen_external_id="abc"),
                     max_results=3, **BUDGET)
    p = seen[0].url.params
    assert seen[0].url.path == "/2/tweets/search/recent"
    assert p["query"] == "(ポップアップ OR 팝업) -is:retweet"
    assert p["max_results"] == "10"            # search 최소 10
    assert "since_id" not in p                 # 숫자가 아니면 since_id 안 붙임


def test_account_min_max_results(tweets_json):
    _, seen = _run(lambda req: httpx.Response(200, json=tweets_json), _account(), max_results=1, **BUDGET)
    assert seen[0].url.params["max_results"] == "5"


def test_pagination_stops_at_read_cap(tweets_json):
    page = {**tweets_json, "meta": {**tweets_json["meta"], "next_token": "NEXT"}}
    # 페이지당 2건, max_results 20, cap 25: 2+20 ≤ 25 → 2페이지, 4+20 ≤ 25 → 3페이지, 6+20 > 25 → 중단
    out, seen = _run(lambda req: httpx.Response(200, json=page), _account(),
                     max_pages=10, per_run_read_cap=25, **BUDGET)
    assert len(seen) == 3
    assert seen[1].url.params["pagination_token"] == "NEXT"
    assert out.last_seen_external_id == "1860000000000000002"


def test_default_single_page(tweets_json):
    page = {**tweets_json, "meta": {**tweets_json["meta"], "next_token": "NEXT"}}
    _, seen = _run(lambda req: httpx.Response(200, json=page), _account(), **BUDGET)
    assert len(seen) == 1


# ---------- 재시도 / 오류 ----------
@pytest.mark.parametrize("status", [429, 500, 503])
def test_retry_429_5xx_then_ok(status, tweets_json):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status) if len(calls) == 1 else httpx.Response(200, json=tweets_json)

    out, seen = _run(handler, _account(), **BUDGET)
    assert len(out.items) == 2 and len(seen) == 2


@pytest.mark.parametrize("status", [400, 401, 403])
def test_4xx_no_retry(status):
    out, seen = _run(lambda req: httpx.Response(status), _account(), **BUDGET)
    assert isinstance(out, ApiError) and out.status == status and len(seen) == 1


def test_error_message_has_no_token():
    out, seen = _run(lambda req: httpx.Response(401), _account(), **BUDGET)
    assert seen[0].headers["authorization"].endswith(FAKE_TOKEN)
    assert FAKE_TOKEN not in repr(out) + "".join(traceback.format_exception(out))


# ---------- 빈 응답 · 필수 필드 누락 ----------
def test_no_data_no_meta_is_layout_changed():
    out, _ = _run(lambda req: httpx.Response(200, json={"errors": []}), _account(), **BUDGET)
    assert isinstance(out, LayoutChanged)


def test_empty_result_keeps_last_seen():
    out, _ = _run(lambda req: httpx.Response(200, json={"meta": {"result_count": 0}}),
                  _account(last_seen_external_id="123"), **BUDGET)
    assert out.items == [] and out.last_seen_external_id == "123"


def test_tweet_missing_fields_does_not_crash():
    data = {"data": [{"id": "5"}, {"text": "id 없음"}], "meta": {}}
    out, _ = _run(lambda req: httpx.Response(200, json=data), _account(), **BUDGET)
    [item] = out.items                                  # id 없는 트윗은 버림
    assert item.content == "" and item.title is None and item.published_at is None
    assert item.url == "https://x.com/test_official/status/5"
    assert item.raw_data == {"tweet_id": "5", "author_id": None, "lang": None, "urls": [],
                             "media_types": [], "referenced": []}


def test_keyword_without_includes_uses_i_url():
    data = {"data": [{"id": "9", "text": "a", "author_id": "222"}], "meta": {"newest_id": "9"}}
    out, _ = _run(lambda req: httpx.Response(200, json=data), _keyword(), **BUDGET)
    assert out.items[0].url == "https://x.com/i/status/9" and out.items[0].author is None


# ---------- 로그에 토큰 없음 (INFO) ----------
def test_token_not_in_logs(caplog, tweets_json):
    import logging
    caplog.set_level(logging.INFO)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json=tweets_json)

    out, seen = _run(handler, _account(), **BUDGET)
    assert len(out.items) == 2 and len(seen) == 2
    # httpx 요청 로그는 tmdb 모듈 import 여부(테스트 순서)에 따라 나오거나 안 나오므로 X 자체 로그로 캡처 확인
    assert "retry" in caplog.text and "예상 비용" in caplog.text
    assert FAKE_TOKEN not in caplog.text

"""TMDB 컬렉터 ("어디서 방영"만). 네트워크 없음: httpx.MockTransport.

픽스처 tmdb_*.json 은 실제 응답이 아니라 공식 문서 형태를 보고 손으로 만든 가짜 데이터 (응답 형식 미검증).
"""
import asyncio
import json
import traceback
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from src.collectors import base_api_collector
from src.collectors.api.tmdb import ATTRIBUTION, TmdbCollector
from src.collectors.base_api_collector import ApiError
from src.collectors.registry import build_collector
from src.collectors.scraping.base_scraper import LayoutChanged
from src.config.settings import settings

FAKE_V3 = "fake-tmdb-v3-key-0000"
FAKE_V4 = "eyJfake.tmdb.v4token"

_seq = iter(range(10**6))


def _source(**cfg):
    # 게이트가 소스 이름별 공유 → 테스트마다 새 이름 + 간격 0
    conf = {"delay_ms": 0, **cfg}
    return SimpleNamespace(name=f"tmdb-t{next(_seq)}", base_url=None, cfg=lambda k, d=None: conf.get(k, d))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def _no_sleep(_):
        return None
    monkeypatch.setattr(base_api_collector, "_sleep", _no_sleep)


@pytest.fixture(autouse=True)
def tmdb_key(monkeypatch):
    monkeypatch.setattr(settings, "TMDB_API_KEY", SecretStr(FAKE_V3))


@pytest.fixture
def search_json(fixture_text):
    return json.loads(fixture_text("tmdb_search_tv.json"))


@pytest.fixture
def detail_json(fixture_text):
    return json.loads(fixture_text("tmdb_tv_900001.json"))


def _run(handler, params, target=None, **cfg):
    """→ (CollectResult 또는 예외, collector, 요청 목록)"""
    seen: list[httpx.Request] = []

    def wrapped(req):
        seen.append(req)
        return handler(req)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as client:
            c = TmdbCollector(_source(**cfg), client=client)
            try:
                return await c.collect(target, params), c
            except Exception as exc:   # noqa: BLE001 — 테스트에서 예외를 값으로 비교
                return exc, c
    out, c = asyncio.run(run())
    return out, c, seen


def _ok_handler(search_json, detail_json):
    def handler(req):
        if req.url.path.endswith("/search/tv"):
            return httpx.Response(200, json=search_json)
        return httpx.Response(200, json=detail_json)
    return handler


ONE = {"items": [{"anime_id": 7, "title": "장송의 프리렌"}]}


# ---------- 규약 ----------
def test_registry_contract():
    c = build_collector(SimpleNamespace(name="tmdb", base_url=None, cfg=lambda k, d=None: d), None)
    assert isinstance(c, TmdbCollector)
    asyncio.run(c.aclose())


# ---------- 정상 흐름 ----------
def test_search_then_detail_builds_item(search_json, detail_json):
    out, _, seen = _run(_ok_handler(search_json, detail_json), ONE)
    assert [r.url.path for r in seen] == ["/3/search/tv", "/3/tv/900001"]
    s = seen[0].url.params
    assert s["query"] == "장송의 프리렌" and s["language"] == "ko-KR" and s["include_adult"] == "false"
    # 상세는 1회, append_to_response 는 watch/providers 만
    assert seen[1].url.params["append_to_response"] == "watch/providers"

    [item] = out.items
    assert item.external_id == "tv:900001"
    assert item.url == "https://www.themoviedb.org/tv/900001"
    assert item.title == "장송의 프리렌"
    assert item.content is None and item.images is None
    rd = item.raw_data
    assert rd["streaming"] == ["netflix", "disney_plus"]      # id 매핑 + 이름 보조 매핑, 중복 제거
    assert rd["other_providers"] == ["Laftel"]                # 매핑 안 된 건 따로
    assert "U-NEXT" not in rd["other_providers"]              # 다른 지역 제외
    assert "Google Play Movies" not in rd["other_providers"]  # rent/buy 제외
    assert rd["justwatch_link"].startswith("https://www.themoviedb.org/tv/900001/watch")
    assert rd["region"] == "KR" and rd["tmdb_id"] == 900001 and rd["anime_id"] == 7
    assert rd["title_original"] == "葬送のフリーレン" and rd["match_score"] >= 85
    assert rd["attribution"] == ATTRIBUTION
    for banned in ("overview", "poster_path", "seasons", "vote_average", "alternative_titles"):
        assert banned not in rd
    json.dumps(rd)   # JSONB 저장 가능
    days = (datetime.fromisoformat(rd["cache_expires_at"]) - datetime.fromisoformat(rd["fetched_at"])).days
    assert days == 180


def test_cache_days_capped_at_180(search_json, detail_json):
    out, _, _ = _run(_ok_handler(search_json, detail_json), ONE, cache_max_days=400)
    rd = out.items[0].raw_data
    assert (datetime.fromisoformat(rd["cache_expires_at"]) - datetime.fromisoformat(rd["fetched_at"])).days == 180


def test_tmdb_id_given_skips_search_and_season_in_external_id(detail_json):
    params = {"items": [{"anime_id": 7, "title": "x", "tmdb_id": 900001, "season": 2}]}
    out, _, seen = _run(lambda req: httpx.Response(200, json=detail_json), params)
    assert [r.url.path for r in seen] == ["/3/tv/900001"]
    assert out.items[0].external_id == "tv:900001:s2"
    assert out.items[0].raw_data["season_number"] == 2 and out.items[0].raw_data["match_score"] is None


def test_target_single_item_and_year(search_json, detail_json):
    target = SimpleNamespace(anime_id=9, value="장송의 프리렌")
    out, _, seen = _run(_ok_handler(search_json, detail_json), None, target=target)
    assert out.items[0].raw_data["anime_id"] == 9
    out, _, seen = _run(_ok_handler(search_json, detail_json),
                        {"items": [{"anime_id": 1, "title": "장송의 프리렌", "year": 2023}]})
    assert seen[0].url.params["first_air_date_year"] == "2023"


def test_batch_size_limits_items(detail_json):
    items = [{"anime_id": i, "title": "t", "tmdb_id": 900001} for i in range(5)]
    out, _, seen = _run(lambda req: httpx.Response(200, json=detail_json), {"items": items, "batch_size": 3})
    assert len(seen) == 3 and len(out.items) == 3


# ---------- 인증 ----------
def test_v3_key_goes_to_query(search_json, detail_json):
    _, _, seen = _run(_ok_handler(search_json, detail_json), ONE)
    assert seen[0].url.params["api_key"] == FAKE_V3 and "authorization" not in seen[0].headers


def test_v4_token_goes_to_header(monkeypatch, search_json, detail_json):
    monkeypatch.setattr(settings, "TMDB_API_KEY", SecretStr(FAKE_V4))
    _, _, seen = _run(_ok_handler(search_json, detail_json), ONE)
    assert seen[0].headers["authorization"] == f"Bearer {FAKE_V4}" and "api_key" not in seen[0].url.params


@pytest.mark.parametrize("value", [None, SecretStr("")])
def test_missing_key_raises_before_request(monkeypatch, value):
    monkeypatch.setattr(settings, "TMDB_API_KEY", value)
    out, _, seen = _run(lambda req: httpx.Response(200, json={}), ONE)
    assert isinstance(out, RuntimeError) and seen == []


# ---------- 재시도 / 오류 ----------
@pytest.mark.parametrize("status", [429, 500, 503])
def test_retry_429_5xx_then_ok(status, search_json, detail_json):
    ok = _ok_handler(search_json, detail_json)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status) if len(calls) == 1 else ok(req)

    out, _, seen = _run(handler, ONE)
    assert len(out.items) == 1 and len(seen) == 3   # search 실패1 + search + detail


def test_retry_exhausted_raises():
    out, _, seen = _run(lambda req: httpx.Response(503), ONE)
    assert isinstance(out, ApiError) and out.status == 503
    assert len(seen) == settings.HTTP_MAX_RETRIES


@pytest.mark.parametrize("status", [400, 401, 403])
def test_4xx_no_retry_and_raises(status):
    out, _, seen = _run(lambda req: httpx.Response(status), ONE)
    assert isinstance(out, ApiError) and out.status == status and len(seen) == 1


def test_error_message_has_no_key():
    out, _, seen = _run(lambda req: httpx.Response(401), ONE)
    assert FAKE_V3 in str(seen[0].url)       # 키가 실제로 URL 에 실렸는데도
    text = repr(out) + "".join(traceback.format_exception(out))
    assert FAKE_V3 not in text               # 에러·traceback 에는 없다


def test_404_is_miss_and_job_continues(detail_json):
    params = {"items": [{"anime_id": 1, "title": "a", "tmdb_id": 404404},
                        {"anime_id": 2, "title": "b", "tmdb_id": 900001}]}

    def handler(req):
        return httpx.Response(404) if "404404" in req.url.path else httpx.Response(200, json=detail_json)

    out, c, _ = _run(handler, params)
    assert [i.raw_data["anime_id"] for i in out.items] == [2]
    assert c.misses == [{"anime_id": 1, "title": "a", "tmdb_id": 404404, "reason": "not_found"}]


# ---------- 매칭 ----------
def test_below_threshold_is_not_matched(search_json):
    params = {"items": [{"anime_id": 3, "title": "진격의 거인"}]}
    out, c, seen = _run(lambda req: httpx.Response(200, json=search_json), params)
    assert out.items == [] and [r.url.path for r in seen] == ["/3/search/tv"]   # 상세 호출 안 함
    assert c.misses[0]["reason"] == "no_match"


def test_non_animation_result_ignored(detail_json):
    # 제목이 완전히 같아도 genre 16 이 없으면 매칭하지 않음
    search = {"results": [{"id": 1, "name": "장송의 프리렌", "original_name": "x", "genre_ids": [18]}]}
    out, c, _ = _run(lambda req: httpx.Response(200, json=search), ONE)
    assert out.items == [] and c.misses[0]["reason"] == "no_match"


# ---------- 빈 응답 · 필수 필드 누락 ----------
def test_search_without_results_key_is_layout_changed():
    out, _, _ = _run(lambda req: httpx.Response(200, json={"page": 1}), ONE)
    assert isinstance(out, LayoutChanged)


def test_search_empty_results_is_miss():
    out, c, _ = _run(lambda req: httpx.Response(200, json={"results": []}), ONE)
    assert out.items == [] and c.misses[0]["reason"] == "no_match"


def test_detail_without_id_is_layout_changed():
    params = {"items": [{"anime_id": 1, "title": "a", "tmdb_id": 5}]}
    out, _, _ = _run(lambda req: httpx.Response(200, json={"name": "a"}), params)
    assert isinstance(out, LayoutChanged)


def test_detail_minimal_keys_does_not_crash():
    # watch/providers·name·original_name·link 가 전부 없어도 None/빈 목록
    search = {"results": [{"id": 5, "genre_ids": [16], "name": "장송의 프리렌"}]}   # original_name 없음

    def handler(req):
        return httpx.Response(200, json=search if req.url.path.endswith("/search/tv") else {"id": 5})

    out, _, _ = _run(handler, ONE)
    rd = out.items[0].raw_data
    assert rd["streaming"] == [] and rd["other_providers"] == [] and rd["justwatch_link"] is None
    assert rd["title_ko"] is None and out.items[0].title is None


def test_providers_with_null_fields_do_not_crash():
    detail = {"id": 5, "watch/providers": {"results": {"KR": {"flatrate": [{"provider_id": None}, {}]}}}}
    params = {"items": [{"anime_id": 1, "title": "a", "tmdb_id": 5}]}
    out, _, _ = _run(lambda req: httpx.Response(200, json=detail), params)
    assert out.items[0].raw_data["streaming"] == [] and out.items[0].raw_data["other_providers"] == []

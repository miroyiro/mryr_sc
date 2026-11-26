"""애니시아: 편성표 응답 → CollectedItem → 방영 이벤트. fixtures = 2026-11-24 실제 응답 (week1 전체, week8 앞 3건)."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from src.collectors.api.anissia import AnissiaCollector
from src.collectors.base_api_collector import ApiError
from src.models.enums import ProcessedCategory
from src.parsers.anissia_parser import AnissiaParser


def _source():
    return SimpleNamespace(name="anissia-test", base_url=None, cfg=lambda k, d=None: {"delay_ms": 0}.get(k, d))


def _collector():
    return AnissiaCollector(_source(), client=httpx.AsyncClient())


def _week(fixture_text, n):
    return json.loads(fixture_text(f"anissia_week{n}.json"))["data"]


def test_parse_item_weekday(fixture_text):
    items = _collector().parse_items(_week(fixture_text, 1), 1)
    assert len(items) == 6
    first = items[0]
    assert first["anissia_no"] == 3463 and first["title_ko"] == "바람의 저편"
    assert first["broadcast_weekday"] == 0          # 애니시아 1 = 월요일 = Python weekday 0
    assert first["broadcast_time"] == "00:00"
    assert first["end_date"] == ""                  # 종영일 미정은 빈 문자열


def test_to_items_week1(fixture_text):
    c = _collector()
    anime = c.parse_items(_week(fixture_text, 1), 1)
    items = c.to_items(anime, today=date(2026, 11, 24))      # 화요일 → 다음 14일 중 월요일 = 11/30, 12/7
    assert len(items) == 5 * 2                               # ON 5개 × 2회 (OFF 1개 제외)
    assert "3486-20261130" not in {i.external_id for i in items}   # PSYREN = OFF(결방)
    first = items[0]
    assert first.external_id == "3463-20261130"
    assert first.title == "바람의 저편"
    assert first.url == "https://anissia.net/anime/3463"
    assert first.raw_data["broadcast_date"] == "2026-11-30"
    assert first.content is None and first.images is None


def test_to_items_dedup(fixture_text):
    c = _collector()
    anime = c.parse_items(_week(fixture_text, 1), 1)
    assert len(c.to_items(anime + anime, today=date(2026, 11, 24))) == 10


def test_to_items_week8_special_dates(fixture_text):
    c = _collector()
    anime = c.parse_items(_week(fixture_text, 8), 8)
    ids = [i.external_id for i in c.to_items(anime, today=date(2026, 12, 25))]   # 12/25 ~ 1/7
    assert ids == ["3534-20261231", "2900-20270102", "3630-20270105"]
    assert c.to_items(anime, today=date(2026, 11, 24)) == []                     # 14일 밖


def test_fetch_week_envelope(fixture_text):
    body = fixture_text("anissia_week1.json")

    async def run(handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await AnissiaCollector(_source(), client=client).fetch_week(1)

    items = asyncio.run(run(lambda req: httpx.Response(200, text=body)))
    assert len(items) == 6
    with pytest.raises(ApiError):
        asyncio.run(run(lambda req: httpx.Response(200, json={"code": "fail", "data": None})))


def _raw(item):
    return SimpleNamespace(title=item.title, content=None, raw_data=item.raw_data,
                           external_id=item.external_id, url=item.url)


def test_parser_broadcast_event(fixture_text):
    c = _collector()
    items = c.to_items(c.parse_items(_week(fixture_text, 1), 1), today=date(2026, 11, 24))
    item = next(i for i in items if i.external_id == "3530-20261130")   # 여친의 친구 01:05
    parsed = AnissiaParser().parse(_raw(item), source_name="anissia")
    assert parsed.category == ProcessedCategory.BROADCAST
    assert parsed.keywords == ["여친의 친구", "彼女の友達"]
    ev = parsed.event_data
    assert ev["type"] == "broadcast" and ev["category"] == "anime" and ev["source"] == "anissia"
    assert ev["start_at"] == "2026-11-30T01:05:00+09:00"
    assert ev["is_all_day"] is False
    assert ev["source_id"] == "3530-20261130"


def test_parser_special_date_all_day(fixture_text):
    c = _collector()
    item = c.to_items(c.parse_items(_week(fixture_text, 8), 8), today=date(2026, 12, 25))[0]
    ev = AnissiaParser().parse(_raw(item), source_name="anissia").event_data
    assert ev["start_at"] == "2026-12-31T00:00:00+09:00"
    assert ev["is_all_day"] is True            # 8주차는 시간 없음 → 종일


@pytest.mark.parametrize("body", [
    [{"animeNo": 1, "subject": "예전 형식"}],   # 공식 문서(2024-06)의 배열 단독 응답 = 예전 형식
    {"code": "ok", "data": None},
    {"code": "fail", "data": []},
])
def test_fetch_week_rejects_other_shapes(body):
    async def run():
        handler = lambda req: httpx.Response(200, json=body)   # noqa: E731
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await AnissiaCollector(_source(), client=client).fetch_week(1)

    with pytest.raises(ApiError):
        asyncio.run(run())


def test_raw_data_fields(fixture_text):
    """x 는 x_url 로 원문만, thumbnail·문자열 week 는 raw_data 에 안 남김."""
    first = _collector().parse_items(_week(fixture_text, 1), 1)[0]
    assert first["x_url"] == "https://x.com/kanatakara_anm"
    assert "thumbnail" not in first and "x" not in first
    assert first["week"] == 1                                   # 응답의 "1"(문자열) 이 아니라 요청한 주차(int)
    no_x = _collector().parse_item({**_week(fixture_text, 1)[0], "x": ""}, 1)
    assert "x_url" not in no_x


def test_empty_start_end_date(fixture_text):
    """startDate·endDate 가 "" 여도 기간 제한 없이 요일 계산 (실제 item 에서 값만 비운 사본)."""
    item = {**_week(fixture_text, 1)[0], "startDate": "", "endDate": ""}
    c = _collector()
    items = c.to_items(c.parse_items([item], 1), today=date(2026, 11, 24))
    assert [i.external_id for i in items] == ["3463-20261130", "3463-20261207"]

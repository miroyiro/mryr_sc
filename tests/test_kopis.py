"""KOPIS: 상세 → CollectedItem → 공연 이벤트.

위쪽 테스트는 픽스처 없이 돈다. 아래쪽(실제 응답)은 tests/fixtures/kopis_*.xml 이 있을 때만 (키가 필요해서 명주가 저장).
"""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from src.collectors import base_api_collector
from src.collectors.api.kopis import KopisCollector
from src.config.settings import settings
from src.models.enums import ProcessedCategory
from src.parsers.kopis_parser import KopisParser, cast_names, parse_kopis_date
from tests.conftest import FIXTURES


def _source():
    return SimpleNamespace(name="kopis-test", base_url=None, cfg=lambda k, d=None: {"delay_ms": 0}.get(k, d))


def _collector():
    return KopisCollector(_source(), client=httpx.AsyncClient())


def _raw(item):
    return SimpleNamespace(title=item.title, content=None, raw_data=item.raw_data,
                           external_id=item.external_id, url=item.url)


DETAIL = {
    "mt20id": "PF999999", "title": "Ado WORLD TOUR in Seoul", "venue": "KSPO DOME",
    "start_date": "2026.12.20", "end_date": "2026.12.21", "cast": "Ado 등", "visit": "Y",
    "updated_at": "2026-11-20 10:00:00", "poster_url": "http://www.kopis.or.kr/upload/x.gif",
}


def test_cast_names():
    assert cast_names("Ado, 요루시카 등") == ["Ado", "요루시카"]
    assert cast_names("YOASOBI") == ["YOASOBI"]
    assert cast_names(None) == []


def test_parse_kopis_date():
    assert parse_kopis_date("2026.12.20").isoformat() == "2026-12-20"
    assert parse_kopis_date("2026-12-20") is None


def test_to_item():
    item = _collector().to_item(DETAIL)
    assert item.external_id == "PF999999"
    assert item.url.endswith("mt20Id=PF999999")
    assert item.published_at.isoformat() == "2026-11-20T10:00:00+09:00"
    assert item.content is None and item.images is None     # 포스터는 raw_data 에만
    assert item.raw_data["poster_url"].endswith("x.gif")


def test_parser_concert_event():
    parsed = KopisParser().parse(_raw(_collector().to_item(DETAIL)), source_name="kopis")
    assert parsed.category == ProcessedCategory.CONCERT
    assert parsed.keywords == ["Ado"]
    ev = parsed.event_data
    assert ev["type"] == "concert" and ev["category"] == "jpop" and ev["source"] == "kopis"
    assert ev["start_at"] == "2026-12-20T00:00:00+09:00"
    assert ev["end_at"] == "2026-12-21T23:59:00+09:00"
    assert ev["venue"] == "KSPO DOME" and ev["is_all_day"] is True
    assert ev["source_id"] == "PF999999"


def test_parser_bad_date_leaves_event_empty():
    parsed = KopisParser().parse(_raw(_collector().to_item({**DETAIL, "start_date": "미정"})), source_name="kopis")
    assert parsed.event_data is None          # → 검수에서 관리자가 날짜 입력 (자동 게시 안 됨)


# ---------------------------------------------------------------- 실제 응답 픽스처
def _need(*names):
    missing = [n for n in names if not (FIXTURES / n).exists()]
    if missing:
        pytest.skip(f"픽스처 없음: {missing} (save_kopis_fixture.py 로 저장)")


def test_real_list(fixture_text):
    _need("kopis_list.xml")
    rows = _collector().parse_list(fixture_text("kopis_list.xml"))
    assert 1 <= len(rows) <= 5
    assert all(r["mt20id"] and r["title"] for r in rows)


def test_real_detail_format(fixture_text):
    """실제 상세 응답: 날짜 '2026.12.12', updatedate 소수 초, 출연진 '… 등'."""
    _need("kopis_detail_visit_n.xml")
    detail = _collector().parse_detail(fixture_text("kopis_detail_visit_n.xml"))
    assert detail["mt20id"] == "PF307351" and detail["visit"] == "N"
    item = _collector().to_item(detail)
    assert item.published_at.isoformat() == "2026-11-24T15:00:03.042720+09:00"
    assert detail["booking_sites"][0]["name"] == "네이버N예약"
    parsed = KopisParser().parse(_raw(item), source_name="kopis")
    assert parsed.keywords[:2] == ["정화", "강한성"] and "등" not in parsed.keywords[-1]
    assert parsed.event_data["start_at"] == "2026-12-12T00:00:00+09:00"
    assert parsed.event_data["end_at"] == "2026-12-12T23:59:00+09:00"


def test_collect_keeps_only_visit_y(fixture_text, monkeypatch):
    """목록 → 상세 → visit=Y 만 남는지 (전 기간 구간을 돌므로 같은 공연은 한 번만).
    실제 응답에 visit=Y 표본이 없어서(앞 60건 0개), visit_n 응답에서 <visit> 값만 Y 로 바꾼 사본을 씀."""
    _need("kopis_list.xml", "kopis_detail_visit_n.xml")
    monkeypatch.setattr(settings, "KOPIS_API_KEY", SecretStr("k"))

    async def _no_sleep(_):
        return None
    monkeypatch.setattr(base_api_collector, "_sleep", _no_sleep)

    list_xml = fixture_text("kopis_list.xml")
    n = fixture_text("kopis_detail_visit_n.xml")
    y = n.replace("<visit>N</visit>", "<visit>Y</visit>")
    assert y != n
    first_id = _collector().parse_list(list_xml)[0]["mt20id"]

    def handler(req):
        if req.url.path.endswith("/pblprfr"):
            return httpx.Response(200, text=list_xml)
        return httpx.Response(200, text=y if req.url.path.endswith(first_id) else n)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await KopisCollector(_source(), client=client).collect(None, {"afterdate": "20261101"})

    result = asyncio.run(run())
    assert [i.external_id for i in result.items] == [first_id]

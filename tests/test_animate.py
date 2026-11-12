import asyncio
from types import SimpleNamespace

import httpx

from src.collectors.scraping.animate import AnimateEventCollector, parse_detail, parse_list, parse_period
from src.models.enums import ProcessedCategory
from src.parsers.animate_parser import AnimateEventParser, title_keywords


def test_parse_list(fixture_text):
    items = parse_list(fixture_text("animate_list.html"))
    assert [i.external_id for i in items] == ["520", "519", "518", "517"]
    last = items[-1]
    assert last.title == "약사의 혼잣말 animate 페어 아이스크림/요새"
    assert last.url.endswith("/board/view.php?bdId=event&sno=517")
    assert last.raw_data["label"] == "페어"
    assert last.raw_data["start"] == "2026-11-07T00:00:00+09:00"
    assert last.raw_data["end"] == "2026-11-22T23:59:00+09:00"
    assert last.content is None


def test_parse_detail_venue_only(fixture_text):
    d = parse_detail(fixture_text("animate_view_517.html"))
    assert d["venues"] == ["홍대점", "잠실롯데점", "부산점", "수원점", "온라인샵"]
    assert set(d) == {"venues", "venue_text"}   # 본문은 돌려주지 않음


def test_parse_period_bad():
    assert parse_period("이벤트기간 미정") == (None, None)


def _raw(item, extra=None):
    return SimpleNamespace(title=item.title, content=None, url=item.url, external_id=item.external_id,
                           raw_data={**item.raw_data, **(extra or {})})


def test_animate_parser(fixture_text):
    item = parse_list(fixture_text("animate_list.html"))[-1]
    detail = parse_detail(fixture_text("animate_view_517.html"))
    parsed = AnimateEventParser().parse(_raw(item, detail), source_name="animate")
    assert parsed.category is ProcessedCategory.FAIR
    assert parsed.keywords == ["약사의 혼잣말"]
    ev = parsed.event_data
    assert ev["type"] == "fair" and ev["category"] == "anime" and ev["source"] == "animate"
    assert ev["source_id"] == "517"
    assert ev["venue"] == "애니메이트 홍대점/잠실롯데점/부산점/수원점"
    assert ev["start_at"] == "2026-11-07T00:00:00+09:00" and ev["is_all_day"] is True


def test_title_keywords_bracket():
    assert title_keywords("『스틸 볼 런: 죠죠의 기묘한 모험』 방영 시작 기념 『죠죠의 기묘한 모험』페어 in animate 3탄") == [
        "스틸 볼 런: 죠죠의 기묘한 모험", "죠죠의 기묘한 모험"]


def test_collect_incremental(fixture_text):
    """last_seen=518 → 519, 520 만 상세 요청. robots·간격은 MockTransport 로 대체."""
    calls = []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /board/\n")
        if req.url.path == "/board/list.php":
            return httpx.Response(200, text=fixture_text("animate_list.html"))
        return httpx.Response(200, text=fixture_text("animate_view_517.html"))

    source = SimpleNamespace(name="animate-test", base_url="https://www.animate-onlineshop.co.kr",
                             cfg=lambda k, d=None: {"delay_ms": 0}.get(k, d))
    target = SimpleNamespace(value="https://www.animate-onlineshop.co.kr/board/list.php?bdId=event&period=all",
                             last_seen_external_id="518")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await AnimateEventCollector(source, client=client).collect(target)

    result = asyncio.run(run())
    assert [i.external_id for i in result.items] == ["519", "520"]
    assert result.last_seen_external_id == "520"
    assert sum("view.php" in c for c in calls) == 2

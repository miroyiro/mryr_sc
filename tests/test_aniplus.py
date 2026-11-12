import json

from src.collectors.scraping.aniplus import parse_news_sitemap
from src.collectors.scraping.aniplus_simulcast import build_items, season_key, split_version


def test_news_sitemap(fixture_bytes):
    items = parse_news_sitemap(fixture_bytes("aniplus_news_sitemap.xml"))
    assert [i.external_id for i in items] == ["news/1492", "news/1491", "news/1490"]
    assert items[0].title.startswith("“너무 최고인")
    assert "『원피스』 & AiNA" in items[0].title          # &amp; 디코딩
    assert items[1].title.startswith('"나루토와')
    assert items[0].published_at.isoformat() == "2026-11-10T20:27:01+09:00"
    assert items[0].content is None


def test_season_key():
    assert season_key("fall", 2026) == ("fall", 2026, "202610")
    assert season_key("Winter", 2027)[2] == "202701"


def test_split_version():
    assert split_version("템빨 ~아이템의 힘~ (더빙)") == ("템빨 ~아이템의 힘~", "dub")
    assert split_version("리락쿠마") == ("리락쿠마", None)


def test_build_items(fixture_text):
    titles = json.loads(fixture_text("aniplus_simulcast_202610.json"))
    items = build_items(titles + [titles[0]], url="https://www.aniplustv.com/list", season="fall", year=2026)
    assert len(items) == len(titles)                     # 중복 카드 제거
    tem = [i for i in items if i.raw_data["base_title"] == "템빨 ~아이템의 힘~"]
    assert {i.raw_data["version"] for i in tem} == {"dub", "sub"}
    assert items[0].external_id == "202610:템빨 ~아이템의 힘~ (더빙)"
    assert items[0].raw_data["platform"] == "aniplus_tv"

import pytest

from src.collectors.scraping.base_scraper import LayoutChanged
from src.collectors.scraping.laftel import parse_item_page, parse_items_sitemap, split_version


def test_items_sitemap(fixture_bytes):
    assert parse_items_sitemap(fixture_bytes("laftel_items_sitemap.xml")) == [48046, 48045, 11876, 164]


def test_items_sitemap_layout_changed():
    with pytest.raises(LayoutChanged):
        parse_items_sitemap(b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>')


def test_item_page(fixture_text):
    item = parse_item_page(fixture_text("laftel_item_48046.html"), laftel_id=48046,
                           url="https://laftel.net/item/48046")
    assert item.title == "(더빙) 슈가슈가룬"
    assert item.external_id == "item:48046"
    assert item.url == "https://laftel.net/item/48046"
    assert item.raw_data == {"laftel_id": "48046", "base_title": "슈가슈가룬", "version": "dub",
                             "platform": "laftel"}


def test_item_page_missing():
    assert parse_item_page("<html><head></head></html>", laftel_id=1, url="u") is None


def test_split_version_suffix():
    assert split_version("슈가슈가룬 (자막)") == ("슈가슈가룬", "sub")

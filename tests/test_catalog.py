import asyncio
from types import SimpleNamespace

from src.parsers.name_matcher import CatalogName, NameMatcher
from src.services import catalog_service


def _raw(title, **data):
    return SimpleNamespace(title=title, url=data.pop("url", "https://www.aniplustv.com/list"), raw_data=data)


def test_group_and_pick():
    raws = [_raw("템빨 (더빙)", platform="aniplus_tv", base_title="템빨", version="dub"),
            _raw("템빨 (자막)", platform="aniplus_tv", base_title="템빨", version="sub")]
    groups = catalog_service.group_links(raws)
    assert list(groups) == [("aniplus_tv", "템빨")]
    assert catalog_service.pick_link(groups[("aniplus_tv", "템빨")])["version"] == "sub"


def test_link_streaming(monkeypatch):
    sent = []

    class FakeBackend:
        async def upsert_streaming(self, *, anime_id, links):
            sent.append((anime_id, links))
            return len(links)

    monkeypatch.setattr(catalog_service, "get_backend", lambda: FakeBackend())
    matcher = NameMatcher([CatalogName("anime", 7, "슈가슈가룬"), CatalogName("anime", 9, "치토세 군은 라무네 병 속에")])
    raws = [
        _raw("(더빙) 슈가슈가룬", platform="laftel", base_title="슈가슈가룬", version="dub", laftel_id="48046",
             url="https://laftel.net/item/48046"),
        _raw("치토세 군은 라무네 병 속에", platform="aniplus_tv", base_title="치토세 군은 라무네 병 속에"),
        _raw("버텍스 포스", platform="aniplus_tv", base_title="버텍스 포스"),
    ]
    result = asyncio.run(catalog_service.link_streaming(raws, matcher))
    assert result.linked == 2 and result.unmatched == ["버텍스 포스"]
    assert sent[0] == (7, [{"platform": "laftel", "source": "laftel", "url": "https://laftel.net/item/48046",
                            "external_id": "48046", "version": "dub"}])
    assert "버텍스 포스" in result.message()

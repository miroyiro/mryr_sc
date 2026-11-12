"""scrape_source.name (+ target_type) → 컬렉터 클래스.

문자열로 lazy import → 아직 없는 컬렉터(준현 작업 중)가 있어도 서버는 뜬다.
해당 소스 잡만 'collector_not_implemented' 로 실패 기록.
"""
import importlib

from src.models import ScrapeSource, ScrapeTarget
from src.models.enums import TargetType

# (source_name, target_type | None) → "module:Class".  target_type 가 None 이면 그 소스 기본값
_REGISTRY: dict[tuple[str, str | None], str] = {
    # ---- 명주: scraping ----
    ("animate", None): "src.collectors.scraping.animate:AnimateEventCollector",
    ("aniplus", TargetType.SITEMAP): "src.collectors.scraping.aniplus:AniplusNewsCollector",
    ("aniplus", TargetType.SPA_PAGE): "src.collectors.scraping.aniplus_simulcast:AniplusSimulcastCollector",
    ("laftel", None): "src.collectors.scraping.laftel:LaftelSitemapCollector",
    # ---- 준현: api / feed (클래스 이름은 준현과 합의해서 맞추기) ----
    ("kopis", None): "src.collectors.api.kopis:KopisCollector",
    ("anissia", None): "src.collectors.api.anissia:AnissiaCollector",
    ("tmdb", None): "src.collectors.api.tmdb:TmdbCollector",
    ("x", None): "src.collectors.api.x:XCollector",
    ("umj", None): "src.collectors.feed.umj_rss:UmjRssCollector",
    # anilist 는 '수집'이 아니라 리졸빙에서 직접 씀 → services/anilist_resolver.py
}


class CollectorNotImplemented(Exception):
    pass


def resolve_path(source: ScrapeSource, target: ScrapeTarget | None) -> str:
    key_specific = (source.name, target.target_type if target else None)
    path = _REGISTRY.get(key_specific) or _REGISTRY.get((source.name, None))
    if path is None:
        raise CollectorNotImplemented(f"no collector for {key_specific}")
    return path


def build_collector(source: ScrapeSource, target: ScrapeTarget | None):
    path = resolve_path(source, target)
    module_name, class_name = path.split(":")
    try:
        cls = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError) as exc:
        raise CollectorNotImplemented(f"{path} not importable: {exc}") from exc
    return cls(source)

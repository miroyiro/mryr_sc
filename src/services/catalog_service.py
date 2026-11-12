"""카탈로그 보강 (명주): 라프텔 · 애니플러스 동시방영 raw_item → main.anime_streaming.

event/news 와 달리 processed_item(관리자 검수)을 거치지 않는다 (11_changes 문서 '카탈로그 보강 흐름').
대신 '확실한 것만' 넣는다:
  - name_matcher 점수 ≥ AUTO_THRESHOLD(0.92) 인 작품만 backend 로 보냄
  - 그 아래(후보만 있음/없음)는 process_job.error_message 에 목록으로 남김 → 관리자가 보고 별칭 추가
    (anime 별칭이 늘면 다음 실행에서 자동으로 붙음)

backend: POST /internal/catalog/streaming {anime_id, links:[{platform, source, url, external_id, version}]}
  → uq_streaming(anime_id, platform, source) 로 upsert. platform=laftel 이면 anime.laftel_id 도 채움.
"""
import logging
from dataclasses import dataclass, field
from typing import Any

from src.clients.backend_client import get_backend
from src.models import RawItem
from src.parsers.name_matcher import NameMatcher

log = logging.getLogger(__name__)

PLATFORM_SOURCE = {"laftel": "laftel", "aniplus_tv": "aniplus"}   # anime_streaming.platform → .source


@dataclass
class CatalogResult:
    linked: int = 0
    failed: int = 0
    unmatched: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)       # 후보는 있는데 점수 애매 (0.75~0.92)

    def message(self) -> str | None:
        parts = []
        if self.review:
            parts.append(f"review {len(self.review)}: " + " | ".join(self.review[:30]))
        if self.unmatched:
            parts.append(f"unmatched {len(self.unmatched)}: " + " | ".join(self.unmatched[:30]))
        return "\n".join(parts)[:4000] or None


def group_links(raws: list[RawItem]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """(platform, base_title) → links. 더빙/자막 두 장이 한 작품으로 묶임."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in raws:
        data = raw.raw_data or {}
        platform = data.get("platform")
        base = data.get("base_title") or raw.title
        if platform not in PLATFORM_SOURCE or not base:
            continue
        groups.setdefault((platform, base), []).append({
            "platform": platform,
            "source": PLATFORM_SOURCE[platform],
            "url": raw.url,
            "external_id": data.get("laftel_id"),
            "version": data.get("version"),
        })
    return groups


def pick_link(links: list[dict[str, Any]]) -> dict[str, Any]:
    """uq_streaming 이 (anime, platform, source) 라 작품당 1개 → 자막판 우선, 없으면 첫 번째."""
    for link in links:
        if link.get("version") in (None, "sub"):
            return link
    return links[0]


async def link_streaming(raws: list[RawItem], matcher: NameMatcher) -> CatalogResult:
    result = CatalogResult()
    backend = get_backend()
    for (platform, base), links in group_links(raws).items():
        cand = matcher.best([base], kind="anime")
        if cand is None:
            result.unmatched.append(base)
            continue
        if not cand.auto:
            result.review.append(f"{base} → {cand.matched_name}#{cand.id} ({cand.score})")
            continue
        try:
            await backend.upsert_streaming(anime_id=cand.id, links=[pick_link(links)])
            result.linked += 1
        except Exception:  # noqa: BLE001 — 한 작품 실패가 나머지를 막지 않게
            result.failed += 1
            log.exception("upsert_streaming failed: %s %s → anime %s", platform, base, cand.id)
    return result

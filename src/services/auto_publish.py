"""자동 게시 판단 (순수 함수 — DB·네트워크 안 씀). process_service 가 processed_item 마다 부른다.

하나라도 걸리면 자동 게시 안 함 → 항목은 pending 으로 남아 관리자 승인으로 감. 사유는 로그(INFO)에만.
- 공통: 소스 auto_publish=TRUE, 필수값 title·start_at·source_url
- anissia: anime_id 매칭
- kopis: visit=Y(내한) + artist_id 매칭 + 보컬로이드 공연 아님
  보컬로이드는 '하드 제외' 표시만 돌려줌 (rejected 로 바꾸는 건 별도 승인 전까지 안 함)
jpop_hint 는 참고용 (kopis 에서 제목·출연진에 가나가 있거나 별칭에 걸림). 게시 여부에 영향 없음.
"""
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "auto_publish_rules.json"
KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")   # 히라가나·가타카나 (반각은 NFKC 로 전각이 됨)


@dataclass(frozen=True)
class PublishCandidate:
    source_name: str
    source_auto_publish: bool
    title: str | None
    event_data: dict[str, Any] | None
    artist_id: int | None = None
    anime_id: int | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)
    alias_matched: bool = False      # 별칭 목록에 걸렸는지 (호출하는 쪽이 채움)


class PublishDecision(NamedTuple):
    ok: bool
    reasons: tuple[str, ...]          # 비어 있어야 ok
    jpop_hint: bool = False           # 참고용 (사유 아님)
    hard_excluded: bool = False       # 보컬로이드 — 표시만


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


@lru_cache(maxsize=1)
def vocaloid_phrases(path: Path = RULES_PATH) -> tuple[str, ...]:
    rules = json.loads(path.read_text(encoding="utf-8"))
    return tuple(_norm(p) for p in rules["vocaloid_phrases"] if p.strip())


def is_vocaloid(text: str, phrases: tuple[str, ...] | None = None) -> bool:
    t = _norm(text)
    return any(p in t for p in (phrases if phrases is not None else vocaloid_phrases()))


def can_auto_publish(c: PublishCandidate, *, phrases: tuple[str, ...] | None = None) -> PublishDecision:
    reasons: list[str] = []
    ev = c.event_data or {}
    if not c.source_auto_publish:
        reasons.append("source_auto_publish_off")
    if not c.title:
        reasons.append("missing_title")
    if not ev.get("start_at"):
        reasons.append("missing_start_at")
    if not ev.get("source_url"):
        reasons.append("missing_source_url")

    jpop_hint = hard_excluded = False
    if c.source_name == "anissia":
        if not c.anime_id:
            reasons.append("anime_unmatched")
    elif c.source_name == "kopis":
        text = " ".join(filter(None, [c.title, c.raw_data.get("cast")]))
        if c.raw_data.get("visit") != "Y":
            reasons.append("visit_not_y")
        if not c.artist_id:
            reasons.append("artist_unmatched")
        if is_vocaloid(text, phrases):
            reasons.append("vocaloid")
            hard_excluded = True
        jpop_hint = bool(KANA_RE.search(unicodedata.normalize("NFKC", text))) or c.alias_matched
    else:
        reasons.append("no_source_rule")   # 규칙 없는 소스는 안전하게 검수로
    return PublishDecision(ok=not reasons, reasons=tuple(reasons), jpop_hint=jpop_hint, hard_excluded=hard_excluded)

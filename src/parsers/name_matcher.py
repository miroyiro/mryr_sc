"""이름 매처 (명주): 글 제목/키워드 → main.artist / main.anime 1차 후보 (RapidFuzz).

- DB가 분리돼서 main 테이블을 직접 못 읽음 → backend 내부 API(/internal/catalog/names)로 받은
  이름 목록을 메모리에 들고 있음 (TTL 10분)
- 최종 확정은 backend resolver / 관리자. 여기 점수는 processed_item.confidence 로만 기록
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz, process

AUTO_THRESHOLD = 0.92     # 이 이상 = 후보 1순위로 바로 연결
REVIEW_THRESHOLD = 0.75   # 이 이상 = 후보로 남기고 관리자 확인. 미만 = 매칭 없음

_PUNCT_RE = re.compile(r"[\s\-_·:：!！?？~〜「」『』《》()\[\]（）]+")


@dataclass(slots=True, frozen=True)
class CatalogName:
    kind: Literal["artist", "anime"]
    id: int
    name: str          # 한 사람/작품의 여러 표기(한/영/일/로마자)가 각각 한 줄


@dataclass(slots=True)
class MatchCandidate:
    kind: Literal["artist", "anime"]
    id: int
    matched_name: str
    score: float       # 0~1

    @property
    def auto(self) -> bool:
        return self.score >= AUTO_THRESHOLD


def normalize(text: str) -> str:
    """NFKC(전각→반각) + 소문자 + 공백·기호 제거. '프리렌 ' == '프리렌' == 'ﾌﾘｰﾚﾝ' 류 맞추기."""
    text = unicodedata.normalize("NFKC", text).lower()
    return _PUNCT_RE.sub("", text)


class NameMatcher:
    def __init__(self, names: list[CatalogName]):
        self._names = names
        self._norm = [normalize(n.name) for n in names]

    @property
    def size(self) -> int:
        return len(self._names)

    def match(self, text: str, *, kind: Literal["artist", "anime"] | None = None,
              limit: int = 3) -> list[MatchCandidate]:
        query = normalize(text)
        if len(query) < 2:
            return []
        hits = process.extract(query, self._norm, scorer=fuzz.WRatio, limit=limit * 3,
                               score_cutoff=REVIEW_THRESHOLD * 100)
        out: list[MatchCandidate] = []
        seen: set[tuple[str, int]] = set()
        for _, score, idx in hits:
            n = self._names[idx]
            if kind and n.kind != kind:
                continue
            if (n.kind, n.id) in seen:   # 같은 대상의 다른 표기 중복 제거
                continue
            seen.add((n.kind, n.id))
            out.append(MatchCandidate(n.kind, n.id, n.name, round(score / 100, 3)))
            if len(out) >= limit:
                break
        return out

    def best(self, texts: list[str], *, kind: Literal["artist", "anime"] | None = None) -> MatchCandidate | None:
        """키워드 여러 개(『』 속 제목들 + 제목 전체) 중 가장 높은 후보."""
        best: MatchCandidate | None = None
        for t in texts:
            for c in self.match(t, kind=kind, limit=1):
                if best is None or c.score > best.score:
                    best = c
        return best

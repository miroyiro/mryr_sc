"""seed scrape_source rows for the confirmed sources (04_data_sources)

전부 enabled = FALSE 로 넣는다. 키·약관 확인 끝난 소스만 관리자 API로 켠다.
auto_publish = TRUE 는 kopis, anissia 뿐 (나머지는 관리자 승인).
base_url 이 NULL 인 곳은 아직 확인 안 된 것 → TODO.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06
"""
import json

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SCHEMA = "miroyiro_scrap"

# (name, type, base_url, auto_publish, description, config)
SOURCES = [
    ("kopis", "api", "http://www.kopis.or.kr/openApi/restful", True,
     "공연(내한). afterdate 증분 → shcate 필터 → 상세 visit=Y",
     {"delay_ms": 1000, "concurrency": 1, "timeout_ms": 10000}),
    ("anilist", "api", "https://graphql.anilist.co", False,
     "애니 카탈로그. lazy fetch + TTL, alias 배치. bulk seed 금지",
     {"rate_limit_per_min": 30, "concurrency": 1, "timeout_ms": 10000}),
    ("anissia", "api", None, True,
     "국내 방영 요일·시간, 한국어 제목. TODO: base_url·이용조건 확인",
     {"delay_ms": 1000, "concurrency": 1}),
    ("tmdb", "api", "https://api.themoviedb.org/3", False,
     "스트리밍·한국어 줄거리·이미지. 출처표기, 캐시 ≤ 180일",
     {"delay_ms": 300, "concurrency": 2, "cache_max_days": 180}),
    ("x", "api", "https://api.x.com/2", False,
     "아티스트·콜라보카페·작품 공식계정. is_verified 대상만, 원문 수정 금지",
     {"concurrency": 1, "monthly_read_cap": 3000000}),
    ("umj", "feed", "https://www.universal-music.co.jp", False,
     "UMJ RSS (Ado·요루시카·back number)",
     {"delay_ms": 2000, "concurrency": 1}),
    ("laftel", "scraping", "https://laftel.net", False,
     "라프텔에서 보기 링크만 (작품명·URL). 1초+ 간격",
     {"delay_ms": 1500, "concurrency": 1, "store_content": False}),
    ("aniplus", "scraping", "https://news.aniplustv.com", False,
     "뉴스 sitemap 1~3h + 동시방영 SPA 분기 1회. /api/ 호출 금지",
     {"delay_ms": 3000, "concurrency": 1, "store_content": False,
      "sitemap_path": "/news-sitemap.xml", "simulcast_url": None}),
    ("animate", "scraping", None, False,
     "페어·이벤트 게시판 /board/list.php?bdId=event. 10초 간격. TODO: 도메인 확인",
     {"delay_ms": 10000, "concurrency": 1, "store_content": False,
      "board_path": "/board/list.php?bdId=event"}),
    ("manual", "manual", None, False,
     "관리자 수동 등록 (1차 출처 링크 필수)", None),
    ("wikidata", "api", "https://query.wikidata.org/sparql", False,
     "보조(QID·넷플 ID, CC0). 컬렉터 미구현", {"delay_ms": 1000, "concurrency": 1}),
]


def _q(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
        return "'" + value.replace("'", "''") + "'::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def upgrade() -> None:
    rows = ",\n  ".join(
        f"({_q(n)}, {_q(t)}, {_q(u)}, FALSE, {_q(a)}, {_q(d)}, {_q(c)})"
        for n, t, u, a, d, c in SOURCES
    )
    op.execute(
        f"""INSERT INTO {SCHEMA}.scrape_source
  (name, type, base_url, enabled, auto_publish, description, config)
VALUES
  {rows}
ON CONFLICT (name) DO NOTHING"""
    )


def downgrade() -> None:
    names = ", ".join(_q(s[0]) for s in SOURCES)
    # 이미 대상·잡이 붙은 소스는 지우지 않는다 (CASCADE로 수집 이력까지 날아가는 것 방지)
    op.execute(
        f"""DELETE FROM {SCHEMA}.scrape_source s
 WHERE s.name IN ({names})
   AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.scrape_target t WHERE t.source_id = s.id)
   AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.scrape_job    j WHERE j.source_id = s.id)"""
    )

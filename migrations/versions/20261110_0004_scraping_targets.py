"""명주 스크래핑 소스 실제 값 반영 + 기본 수집 대상(scrape_target) 4개

2026-11-10 사이트 직접 확인 결과 (04_data_sources)
- animate : 도메인 확정 https://www.animate-onlineshop.co.kr (0003 에선 NULL·TODO)
            목록은 period=all (최신순, 예정 이벤트 포함)
- aniplus : 동시방영 페이지 https://www.aniplustv.com/list (SPA, 분기 체크박스)
- laftel  : 검색은 SPA라 불가 → /sitemaps/items.xml + 작품 페이지 og:title 방식으로 변경

스키마 변경 없음 (ERD v1.2 그대로: target_type 'sitemap'·'board'·'spa_page' 는 0002 에서 이미 허용).
scrape_source.enabled 는 그대로 FALSE — 관리자 API 로 켠다 (laftel 은 로톡 Q3 답변 전까지 OFF).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""
import json

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SCHEMA = "miroyiro_scrap"

ANIMATE_BASE = "https://www.animate-onlineshop.co.kr"

# name → (base_url, description, config 에 merge 할 값)
SOURCE_UPDATES = {
    "animate": (
        ANIMATE_BASE,
        "페어·이벤트 게시판 목록+새 글 상세(개최장소). 10초 간격, 본문 저장 X",
        {"board_path": "/board/list.php?bdId=event&period=all", "max_detail": 15},
    ),
    "aniplus": (
        "https://news.aniplustv.com",
        "뉴스 sitemap 1~3h + 동시방영 SPA(www.aniplustv.com/list) 분기 1회. /api/ 호출 금지",
        {"simulcast_url": "https://www.aniplustv.com/list"},
    ),
    "laftel": (
        "https://laftel.net",
        "items sitemap → 작품 페이지 og:title (작품명·URL·laftel_id만). 1.5초 간격, id 커서 증분",
        {"sitemap_path": "/sitemaps/items.xml", "batch_size": 100},
    ),
}

# (source_name, target_type, value, crawl_interval_sec)
TARGETS = [
    ("animate", "board", f"{ANIMATE_BASE}/board/list.php?bdId=event&period=all", 6 * 3600),
    ("aniplus", "sitemap", "https://news.aniplustv.com/news-sitemap.xml", 2 * 3600),
    ("aniplus", "spa_page", "https://www.aniplustv.com/list", 7 * 86400),
    ("laftel", "sitemap", "https://laftel.net/sitemaps/items.xml", 86400),
]


def _q(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, dict):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def upgrade() -> None:
    for name, (base_url, desc, cfg) in SOURCE_UPDATES.items():
        op.execute(
            f"""UPDATE {SCHEMA}.scrape_source
   SET base_url = {_q(base_url)}, description = {_q(desc)},
       config = COALESCE(config, '{{}}'::jsonb) || {_q(cfg)}, updated_at = now()
 WHERE name = {_q(name)}"""
        )
    for name, ttype, value, interval in TARGETS:
        # 공식 사이트 고정 URL 이라 is_verified = TRUE (X 계정처럼 사람이 확인할 대상 아님)
        op.execute(
            f"""INSERT INTO {SCHEMA}.scrape_target
  (source_id, target_type, value, is_verified, status, crawl_interval_sec)
SELECT s.id, {_q(ttype)}, {_q(value)}, TRUE, 'active', {interval}
  FROM {SCHEMA}.scrape_source s WHERE s.name = {_q(name)}
ON CONFLICT ON CONSTRAINT uq_target DO NOTHING"""
        )


def downgrade() -> None:
    for name, ttype, value, _ in TARGETS:
        # 이미 수집 이력이 있으면 남김 (CASCADE 로 raw_item 까지 지워지는 것 방지)
        op.execute(
            f"""DELETE FROM {SCHEMA}.scrape_target t
 USING {SCHEMA}.scrape_source s
 WHERE t.source_id = s.id AND s.name = {_q(name)} AND t.value = {_q(value)}
   AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.scrape_job j WHERE j.target_id = t.id)"""
        )
    op.execute(
        f"""UPDATE {SCHEMA}.scrape_source SET base_url = NULL,
       description = '페어·이벤트 게시판 /board/list.php?bdId=event. 10초 간격. TODO: 도메인 확인'
 WHERE name = 'animate'"""
    )
    for name, (_, _, cfg) in SOURCE_UPDATES.items():
        for key in cfg:
            if (name, key) == ("animate", "board_path"):
                op.execute(f"""UPDATE {SCHEMA}.scrape_source
   SET config = config || '{{"board_path": "/board/list.php?bdId=event"}}'::jsonb WHERE name = 'animate'""")
            elif (name, key) == ("aniplus", "simulcast_url"):
                op.execute(f"""UPDATE {SCHEMA}.scrape_source
   SET config = config || '{{"simulcast_url": null}}'::jsonb WHERE name = 'aniplus'""")
            else:
                op.execute(f"UPDATE {SCHEMA}.scrape_source SET config = config - {_q(key)} WHERE name = {_q(name)}")

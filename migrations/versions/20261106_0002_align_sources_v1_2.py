"""align scrap schema with confirmed sources (ERD v1.2)

- scrape_target.target_type : 'official_site' 제거, 'sitemap'·'spa_page' 추가 (ck_target_type)
- processed_item.category   : main.event.type 과 값 통일 ('album'→'release' 등) (ck_processed_category)
- processed_item            : UNIQUE(raw_item_id) 로 재처리 중복 방지 (idx_processed_raw 대체)
- scrape_target             : idx_target_anime 추가

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06

"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCHEMA = "miroyiro_scrap"

TARGET_TYPES_NEW = ("x_account", "rss_feed", "sitemap", "board", "spa_page", "keyword")
TARGET_TYPES_OLD = ("official_site", "x_account", "rss_feed", "board", "keyword")
CATEGORIES_NEW = ("news", "concert", "broadcast", "streaming", "popup",
                  "collabo_cafe", "fair", "exhibition", "release", "etc")
CATEGORIES_OLD = ("news", "concert", "popup", "collabo_cafe", "fair", "album", "etc")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _drop_column_checks(table: str, column: str) -> str:
    """컬럼 하나에 걸린 CHECK를 이름과 상관없이 전부 DROP.
    v1.1은 인라인 CHECK라 이름이 PG 자동 생성(<table>_<column>_check)이라 하드코딩하지 않음."""
    return f"""
DO $$
DECLARE c record;
BEGIN
  FOR c IN
    SELECT con.conname
      FROM pg_constraint con
      JOIN pg_class rel     ON rel.oid = con.conrelid
      JOIN pg_namespace n   ON n.oid = rel.relnamespace
      JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY (con.conkey)
     WHERE con.contype = 'c'
       AND n.nspname = '{SCHEMA}' AND rel.relname = '{table}' AND att.attname = '{column}'
       AND array_length(con.conkey, 1) = 1
  LOOP
    EXECUTE format('ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
"""


def _abort_if(condition_sql: str, message: str) -> str:
    """데이터가 새 제약을 깨면 마이그레이션 전체 중단 (PG는 DDL도 트랜잭션 → 전부 롤백)."""
    return f"""
DO $$
BEGIN
  IF EXISTS ({condition_sql}) THEN
    RAISE EXCEPTION '{message}';
  END IF;
END $$;
"""


UPGRADE_SQL = [
    # 1) 사전 점검: 새 제약을 깨는 데이터가 있으면 중단
    _abort_if(
        f"SELECT 1 FROM {SCHEMA}.scrape_target WHERE target_type = 'official_site'",
        "scrape_target에 official_site 행이 있음 (공식사이트 수집 제외 확정). 먼저 삭제/변경 후 다시 실행",
    ),
    _abort_if(
        f"SELECT raw_item_id FROM {SCHEMA}.processed_item GROUP BY raw_item_id HAVING count(*) > 1",
        "processed_item에 같은 raw_item_id가 2건 이상 있음. 중복 정리 후 다시 실행",
    ),
    # 2) CHECK 교체 = DROP → (데이터 변환) → ADD  (CHECK는 "수정" 명령이 없음)
    #    순서 주의: 옛 CHECK가 살아 있는 동안 'release'로 UPDATE 하면 옛 CHECK에 걸림
    _drop_column_checks("scrape_target", "target_type"),
    f"ALTER TABLE {SCHEMA}.scrape_target ADD CONSTRAINT ck_target_type "
    f"CHECK (target_type IN ({_in_list(TARGET_TYPES_NEW)}))",
    _drop_column_checks("processed_item", "category"),
    f"UPDATE {SCHEMA}.processed_item SET category = 'release' WHERE category = 'album'",
    f"ALTER TABLE {SCHEMA}.processed_item ADD CONSTRAINT ck_processed_category "
    f"CHECK (category IN ({_in_list(CATEGORIES_NEW)}))",
    # 3) 인덱스 → UNIQUE (UNIQUE가 인덱스를 만들어주므로 기존 인덱스는 제거)
    f"DROP INDEX IF EXISTS {SCHEMA}.idx_processed_raw",
    f"ALTER TABLE {SCHEMA}.processed_item ADD CONSTRAINT uq_processed_raw UNIQUE (raw_item_id)",
    # 4) 작품 단위 대상 조회용
    f"CREATE INDEX IF NOT EXISTS idx_target_anime ON {SCHEMA}.scrape_target (anime_id)",
]

DOWNGRADE_SQL = [
    _abort_if(
        f"SELECT 1 FROM {SCHEMA}.scrape_target WHERE target_type IN ('sitemap','spa_page')",
        "sitemap/spa_page 대상이 있어 되돌릴 수 없음. 먼저 정리",
    ),
    _abort_if(
        f"SELECT 1 FROM {SCHEMA}.processed_item WHERE category IN ('broadcast','streaming','exhibition')",
        "v1.1에 없는 category(broadcast/streaming/exhibition) 행이 있어 되돌릴 수 없음",
    ),
    f"DROP INDEX IF EXISTS {SCHEMA}.idx_target_anime",
    f"ALTER TABLE {SCHEMA}.processed_item DROP CONSTRAINT IF EXISTS uq_processed_raw",
    f"CREATE INDEX IF NOT EXISTS idx_processed_raw ON {SCHEMA}.processed_item (raw_item_id)",
    f"ALTER TABLE {SCHEMA}.processed_item DROP CONSTRAINT IF EXISTS ck_processed_category",
    f"UPDATE {SCHEMA}.processed_item SET category = 'album' WHERE category = 'release'",
    f"ALTER TABLE {SCHEMA}.processed_item ADD CONSTRAINT processed_item_category_check "
    f"CHECK (category IN ({_in_list(CATEGORIES_OLD)}))",
    f"ALTER TABLE {SCHEMA}.scrape_target DROP CONSTRAINT IF EXISTS ck_target_type",
    f"ALTER TABLE {SCHEMA}.scrape_target ADD CONSTRAINT scrape_target_target_type_check "
    f"CHECK (target_type IN ({_in_list(TARGET_TYPES_OLD)}))",
]


def upgrade() -> None:
    for sql in UPGRADE_SQL:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE_SQL:
        op.execute(sql)

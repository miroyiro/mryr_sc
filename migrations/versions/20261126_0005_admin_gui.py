"""관리 GUI: admin_user · admin_session + scrape_target 에 메모·verify 기록 3컬럼

- admin_user    : sc 자체 관리자 계정 (main.users 와 별개). 회원가입 없음 → scripts/create_admin.py 로만 생성
- admin_session : 로그인 세션. 쿠키 원문은 저장하지 않고 sha256 만 저장 (DB 가 새도 세션 탈취 불가)
                  로그아웃 = 행 삭제 → 즉시 무효. 만료는 expires_at 으로 판정
- scrape_target : admin_note(메모), verified_by·verified_at(누가·언제 verify 했나)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-26
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

SCHEMA = "miroyiro_scrap"

# asyncpg 는 한 번에 SQL 1문장만 → 리스트로 하나씩 실행 (0001 과 같은 방식)
UPGRADE = [
    f"""CREATE TABLE {SCHEMA}.admin_user (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username      VARCHAR(50)  NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role          VARCHAR(10)  NOT NULL CHECK (role IN ('editor','admin')),
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT uq_admin_username UNIQUE (username)
)""",
    f"""CREATE TRIGGER trg_admin_user_updated_at BEFORE UPDATE ON {SCHEMA}.admin_user
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()""",
    f"""CREATE TABLE {SCHEMA}.admin_session (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admin_user_id BIGINT      NOT NULL REFERENCES {SCHEMA}.admin_user(id) ON DELETE CASCADE,
  token_hash    CHAR(64)    NOT NULL,
  csrf_token    VARCHAR(64) NOT NULL,
  expires_at    TIMESTAMPTZ NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_admin_session_token UNIQUE (token_hash)
)""",
    f"CREATE INDEX idx_admin_session_expires ON {SCHEMA}.admin_session (expires_at)",
    f"ALTER TABLE {SCHEMA}.scrape_target ADD COLUMN admin_note VARCHAR(500) NULL",
    # 계정을 지워도 대상 행은 남기고 '누가' 만 비움
    f"""ALTER TABLE {SCHEMA}.scrape_target ADD COLUMN verified_by BIGINT NULL
  REFERENCES {SCHEMA}.admin_user(id) ON DELETE SET NULL""",
    f"ALTER TABLE {SCHEMA}.scrape_target ADD COLUMN verified_at TIMESTAMPTZ NULL",
]

DOWNGRADE = [
    f"ALTER TABLE {SCHEMA}.scrape_target DROP COLUMN IF EXISTS verified_at",
    f"ALTER TABLE {SCHEMA}.scrape_target DROP COLUMN IF EXISTS verified_by",
    f"ALTER TABLE {SCHEMA}.scrape_target DROP COLUMN IF EXISTS admin_note",
    f"DROP TABLE IF EXISTS {SCHEMA}.admin_session",
    f"DROP TABLE IF EXISTS {SCHEMA}.admin_user",
]


def upgrade() -> None:
    for stmt in UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE:
        op.execute(stmt)

"""init scrap schema (05_erd_final.sql v1.1의 SCRAP 부분)

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# asyncpg는 한 번에 SQL 문장 1개만 실행 가능 → 문장 단위로 나눠서 실행
COMMON = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public",
    r"""CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql""",
    "SET search_path TO miroyiro_scrap, public",
]

TABLES = r"""
CREATE TABLE scrape_source (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name         VARCHAR(50)  NOT NULL,
  type         VARCHAR(10)  NOT NULL CHECK (type IN ('api','feed','scraping','manual')),
  base_url     VARCHAR(255) NULL,
  enabled      BOOLEAN      NOT NULL DEFAULT FALSE,
  auto_publish BOOLEAN      NOT NULL DEFAULT FALSE,
  description  VARCHAR(255) NULL,
  config       JSONB        NULL,
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT uq_source_name UNIQUE (name)
);

CREATE TABLE scrape_target (
  id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id             BIGINT       NOT NULL REFERENCES scrape_source(id) ON DELETE CASCADE,
  target_type           VARCHAR(20)  NOT NULL CHECK (target_type IN ('official_site','x_account','rss_feed','board','keyword')),
  artist_id             BIGINT       NULL,
  anime_id              BIGINT       NULL,
  value                 VARCHAR(500) NOT NULL,
  x_user_id             VARCHAR(30)  NULL,
  is_verified           BOOLEAN      NOT NULL DEFAULT FALSE,
  status                VARCHAR(10)  NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','broken')),
  crawl_interval_sec    INT          NOT NULL DEFAULT 3600,
  last_crawled_at       TIMESTAMPTZ  NULL,
  last_seen_external_id VARCHAR(100) NULL,
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT uq_target UNIQUE (source_id, value)
);
CREATE INDEX idx_target_artist ON scrape_target (artist_id);

CREATE TABLE scrape_schedule (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id        BIGINT      NOT NULL REFERENCES scrape_source(id) ON DELETE CASCADE,
  target_id        BIGINT      NULL     REFERENCES scrape_target(id) ON DELETE CASCADE,
  schedule_type    VARCHAR(10) NOT NULL DEFAULT 'interval' CHECK (schedule_type IN ('interval','cron')),
  interval_minutes INT         NULL,
  cron_expression  VARCHAR(50) NULL,
  enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
  last_run_at      TIMESTAMPTZ NULL,
  next_run_at      TIMESTAMPTZ NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_schedule_shape CHECK (
    (schedule_type = 'interval' AND interval_minutes IS NOT NULL) OR
    (schedule_type = 'cron'     AND cron_expression  IS NOT NULL))
);
CREATE INDEX idx_schedule_next ON scrape_schedule (enabled, next_run_at);

CREATE TABLE scrape_job (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id       BIGINT       NOT NULL REFERENCES scrape_source(id)   ON DELETE CASCADE,
  target_id       BIGINT       NULL     REFERENCES scrape_target(id)   ON DELETE SET NULL,
  schedule_id     BIGINT       NULL     REFERENCES scrape_schedule(id) ON DELETE SET NULL,
  retry_of        BIGINT       NULL     REFERENCES scrape_job(id)      ON DELETE SET NULL,
  target          VARCHAR(500) NULL,
  status          VARCHAR(10)  NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed','cancelled')),
  total_count     INT          NOT NULL DEFAULT 0,
  collected_count INT          NOT NULL DEFAULT 0,
  duplicate_count INT          NOT NULL DEFAULT 0,
  error_count     INT          NOT NULL DEFAULT 0,
  error_message   TEXT         NULL,
  started_at      TIMESTAMPTZ  NULL,
  finished_at     TIMESTAMPTZ  NULL,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_job_status ON scrape_job (status, created_at);

CREATE TABLE raw_item (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id     BIGINT       NOT NULL REFERENCES scrape_source(id) ON DELETE CASCADE,
  scrape_job_id BIGINT       NOT NULL REFERENCES scrape_job(id)    ON DELETE CASCADE,
  external_id   VARCHAR(100) NOT NULL,
  url           VARCHAR(500) NOT NULL,
  title         VARCHAR(300) NULL,
  content       TEXT         NULL,
  author        VARCHAR(100) NULL,
  images        JSONB        NULL,
  published_at  TIMESTAMPTZ  NULL,
  collected_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  raw_data      JSONB        NULL,
  hash          CHAR(64)     NOT NULL,
  CONSTRAINT uq_raw_external UNIQUE (source_id, external_id)
);
CREATE INDEX idx_raw_hash ON raw_item (hash);
CREATE INDEX idx_raw_job  ON raw_item (scrape_job_id);

CREATE TABLE process_job (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scrape_job_id   BIGINT      NULL REFERENCES scrape_job(id) ON DELETE SET NULL,
  status          VARCHAR(10) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed')),
  total_count     INT         NOT NULL DEFAULT 0,
  processed_count INT         NOT NULL DEFAULT 0,
  failed_count    INT         NOT NULL DEFAULT 0,
  error_message   TEXT        NULL,
  started_at      TIMESTAMPTZ NULL,
  finished_at     TIMESTAMPTZ NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE processed_item (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  raw_item_id        BIGINT       NOT NULL REFERENCES raw_item(id)    ON DELETE CASCADE,
  process_job_id     BIGINT       NULL     REFERENCES process_job(id) ON DELETE SET NULL,
  artist_id          BIGINT       NULL,
  anime_id           BIGINT       NULL,
  category           VARCHAR(20)  NOT NULL CHECK (category IN ('news','concert','popup','collabo_cafe','fair','album','etc')),
  title              VARCHAR(200) NOT NULL,
  summary            VARCHAR(500) NULL,
  keywords           JSONB        NULL,
  event_data         JSONB        NULL,
  status             VARCHAR(10)  NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','rejected')),
  confidence         NUMERIC(3,2) NULL,
  reviewed_by        BIGINT       NULL,
  reviewed_at        TIMESTAMPTZ  NULL,
  reject_reason      VARCHAR(255) NULL,
  published_event_id BIGINT       NULL,
  published_news_id  BIGINT       NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_processed_status ON processed_item (status, category);
CREATE INDEX idx_processed_raw    ON processed_item (raw_item_id);

CREATE TABLE scrape_error (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_type    VARCHAR(10)   NOT NULL CHECK (job_type IN ('scrape','process')),
  job_id      BIGINT        NOT NULL,
  raw_item_id BIGINT        NULL REFERENCES raw_item(id) ON DELETE SET NULL,
  type        VARCHAR(50)   NOT NULL,
  message     VARCHAR(1000) NOT NULL,
  stack       TEXT          NULL,
  status      VARCHAR(10)   NOT NULL DEFAULT 'unresolved' CHECK (status IN ('unresolved','resolved','ignored')),
  retry_count INT           NOT NULL DEFAULT 0,
  resolved_at TIMESTAMPTZ   NULL,
  created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_error_job    ON scrape_error (job_type, job_id);
CREATE INDEX idx_error_status ON scrape_error (status, created_at);

CREATE TABLE api_cache (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source     VARCHAR(30)  NOT NULL,
  cache_key  VARCHAR(255) NOT NULL,
  data       JSONB        NOT NULL,
  cached_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ  NOT NULL,
  CONSTRAINT uq_cache_key UNIQUE (source, cache_key)
);
CREATE INDEX idx_cache_expires ON api_cache (expires_at);
"""

TRIGGERS = r"""
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT table_name FROM information_schema.columns
    WHERE column_name = 'updated_at' AND table_schema = 'miroyiro_scrap'
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON miroyiro_scrap.%I
         FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()',
      r.table_name, r.table_name);
  END LOOP;
END $$;
"""

DROP_TABLES = [
    "api_cache", "scrape_error", "processed_item", "process_job",
    "raw_item", "scrape_job", "scrape_schedule", "scrape_target", "scrape_source",
]


def upgrade() -> None:
    for stmt in COMMON:
        op.execute(stmt)
    for stmt in TABLES.split(";"):  # 테이블 DDL 안에는 ; 가 없어서 안전
        if stmt.strip():
            op.execute(stmt)
    op.execute(TRIGGERS)


def downgrade() -> None:
    for t in DROP_TABLES:
        op.execute(f"DROP TABLE IF EXISTS miroyiro_scrap.{t} CASCADE")

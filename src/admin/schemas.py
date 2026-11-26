"""관리 GUI 응답 스키마 — 필드를 '허용 목록'으로 직접 적는다 (모델 통째 직렬화 금지).

Public*  : 비로그인(PUBLIC_READ=true) 응답. 여기 없는 필드는 절대 안 나감.
           금지: raw_data·content·config·base_url·URL·IP·키·error message·stack·x_user_id·메모
Admin*   : 로그인 사용자 응답. 그래도 raw_data·content·stack·config 통째는 안 내보냄.
"""
from datetime import datetime

from pydantic import BaseModel


# --- 비로그인 (화이트리스트) ---
class PublicSourceOut(BaseModel):
    name: str
    type: str
    enabled: bool
    last_job_status: str | None


class PublicTargetOut(BaseModel):
    id: int
    source_name: str
    target_type: str
    handle: str | None        # x_account 일 때만 공개 X 핸들. 다른 타입(URL 등)은 None
    status: str


class PublicJobOut(BaseModel):
    id: int
    source_name: str
    status: str
    total_count: int
    collected_count: int
    duplicate_count: int
    error_count: int
    started_at: datetime | None
    finished_at: datetime | None


class SourceCount(BaseModel):
    source_name: str
    collected: int


class PublicDashboardOut(BaseModel):
    started_at: datetime            # 가동 시작 시각 (첫 잡 생성 시각, 없으면 프로세스 시작)
    source_counts: list[SourceCount]
    recent_jobs: list[PublicJobOut]


# --- 로그인 사용자 ---
class AdminSourceOut(PublicSourceOut):
    id: int
    auto_publish: bool
    description: str | None
    monthly_budget_usd: float | None   # config 중 이 값만 (config 통째 X — 다른 키가 섞일 수 있음)


class AdminTargetOut(BaseModel):
    id: int
    source_id: int
    source_name: str
    target_type: str
    value: str
    status: str
    is_verified: bool
    crawl_interval_sec: int
    last_crawled_at: datetime | None
    admin_note: str | None
    verified_by: int | None
    verified_at: datetime | None
    created_at: datetime


class ErrorTypeCount(BaseModel):
    type: str        # parse_error, http_429 … (유형만. message·stack 원문 X)
    count: int


class AdminDashboardOut(PublicDashboardOut):
    error_counts: list[ErrorTypeCount]


class Page(BaseModel):
    page: int
    limit: int
    total: int


class PublicTargetList(BaseModel):
    data: list[PublicTargetOut]
    meta: Page


class AdminTargetList(BaseModel):
    data: list[AdminTargetOut]
    meta: Page

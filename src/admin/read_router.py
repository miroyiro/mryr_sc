"""/admin/api 읽기 — 대시보드·소스·대상 목록/상세.

모든 라우트가 ReaderDep: 로그인 → Admin* 스키마, 비로그인(PUBLIC_READ=true, GET) → Public* 스키마.
응답은 아래 to_* 함수가 필드를 하나씩 골라 만든다 → 모델에 컬럼이 늘어도 자동으로 새어 나가지 않음.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status

from src.admin.deps import ReaderDep, StoreDep
from src.admin.schemas import (
    AdminDashboardOut, AdminSourceOut, AdminTargetList, AdminTargetOut, ErrorTypeCount, Page,
    PublicDashboardOut, PublicJobOut, PublicSourceOut, PublicTargetList, PublicTargetOut, SourceCount,
)
from src.api.deps import PageDep

router = APIRouter(prefix="/admin/api", tags=["admin:read"])

PROCESS_STARTED_AT = datetime.now(UTC)   # 잡이 하나도 없을 때 '가동 시작 시각' 대신 씀


def _budget(cfg: dict | None) -> float | None:
    v = (cfg or {}).get("monthly_budget_usd")
    return float(v) if isinstance(v, int | float) else None


def to_public_source(s, last_status) -> PublicSourceOut:
    return PublicSourceOut(name=s.name, type=s.type, enabled=s.enabled, last_job_status=last_status)


def to_admin_source(s, last_status) -> AdminSourceOut:
    return AdminSourceOut(name=s.name, type=s.type, enabled=s.enabled, last_job_status=last_status,
                          id=s.id, auto_publish=s.auto_publish, description=s.description,
                          monthly_budget_usd=_budget(s.config))


def to_public_target(t, source_name) -> PublicTargetOut:
    # X 계정만 핸들 공개. sitemap·board 등은 value 가 URL 이라 비로그인에겐 안 보냄
    handle = t.value if t.target_type == "x_account" else None
    return PublicTargetOut(id=t.id, source_name=source_name, target_type=t.target_type,
                           handle=handle, status=t.status)


def to_admin_target(t, source_name) -> AdminTargetOut:
    return AdminTargetOut(
        id=t.id, source_id=t.source_id, source_name=source_name, target_type=t.target_type, value=t.value,
        status=t.status, is_verified=t.is_verified, crawl_interval_sec=t.crawl_interval_sec,
        last_crawled_at=t.last_crawled_at, admin_note=t.admin_note, verified_by=t.verified_by,
        verified_at=t.verified_at, created_at=t.created_at,
    )


def to_public_job(j, source_name) -> PublicJobOut:
    # error_message·target(URL) 은 넣지 않음
    return PublicJobOut(id=j.id, source_name=source_name, status=j.status, total_count=j.total_count,
                        collected_count=j.collected_count, duplicate_count=j.duplicate_count,
                        error_count=j.error_count, started_at=j.started_at, finished_at=j.finished_at)


@router.get("/dashboard", response_model=None)
async def dashboard(viewer: ReaderDep, store: StoreDep) -> PublicDashboardOut | AdminDashboardOut:
    common = dict(
        started_at=await store.first_job_at() or PROCESS_STARTED_AT,
        source_counts=[SourceCount(source_name=n, collected=c) for n, c in await store.collected_counts()],
        recent_jobs=[to_public_job(j, n) for j, n in await store.recent_jobs(10)],
    )
    if viewer is None:
        return PublicDashboardOut(**common)
    errors = [ErrorTypeCount(type=t, count=c) for t, c in await store.error_type_counts()]
    return AdminDashboardOut(**common, error_counts=errors)


@router.get("/sources", response_model=None)
async def sources(viewer: ReaderDep, store: StoreDep) -> list[PublicSourceOut] | list[AdminSourceOut]:
    rows = await store.sources_with_last_status()
    conv = to_public_source if viewer is None else to_admin_source
    return [conv(s, st) for s, st in rows]


@router.get("/targets", response_model=None)
async def targets(
    viewer: ReaderDep, store: StoreDep, page: PageDep, source_id: int | None = Query(None, alias="sourceId"),
) -> PublicTargetList | AdminTargetList:
    rows, total = await store.targets(page, source_id)
    meta = Page(page=page.page, limit=page.limit, total=total)
    if viewer is None:
        return PublicTargetList(data=[to_public_target(t, n) for t, n in rows], meta=meta)
    return AdminTargetList(data=[to_admin_target(t, n) for t, n in rows], meta=meta)


@router.get("/targets/{target_id}", response_model=None)
async def target_detail(target_id: int, viewer: ReaderDep, store: StoreDep) -> PublicTargetOut | AdminTargetOut:
    found = await store.target(target_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "target not found")
    return to_public_target(*found) if viewer is None else to_admin_target(*found)

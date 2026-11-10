"""소스별 동기화 요청 body (api문서 수집/API·수집/스크래핑 행).
공통 규칙 'sync 는 202' 를 따라 바로 결과를 주지 않고 scrape_job 을 큐에 넣는다.
body 값은 scrape_job.target 에 JSON 문자열로 실려 컬렉터의 params 로 전달된다."""
from typing import Literal

from pydantic import BaseModel, Field

Season = Literal["winter", "spring", "summer", "fall"]


class AnissiaSyncRequest(BaseModel):
    weeks: list[int] | None = Field(None, description="생략 시 0~8 전체")


class KopisSyncRequest(BaseModel):
    afterdate: str | None = Field(None, pattern=r"^\d{8}$", description="YYYYMMDD")
    shcate: str | None = None


class SeasonSyncRequest(BaseModel):
    season: Season | None = None
    season_year: int | None = Field(None, ge=1990, le=2100)


class SyncQueuedOut(BaseModel):
    source: str
    job_ids: list[int]
    status: str = "queued"

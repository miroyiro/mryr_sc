from pydantic import BaseModel, Field


class AnimeResolveRequest(BaseModel):
    """새 작품명 리졸빙 요청 (팀 수동 입력 / 스크랩 발견 / 유저 추가요청)."""
    titles: list[str] = Field(min_length=1, max_length=50)


class AnimeRefreshRequest(BaseModel):
    """TTL 지난 작품 재조회 요청 (backend가 화면 열 때 발견)."""
    anilist_ids: list[int] = Field(min_length=1, max_length=50)
    force: bool = False  # TRUE면 TTL 무시


class ResolveCandidate(BaseModel):
    title: str
    anilist_id: int | None
    matched_title: str | None
    score: float
    auto_confirmed: bool  # 신뢰도 높음 → 자동 확정, 아니면 관리자 확인

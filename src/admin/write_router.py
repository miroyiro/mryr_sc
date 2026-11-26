"""/admin/api 쓰기 — 이번 범위는 두 개뿐: 메모(editor 이상) · X 대상 verify(admin).

추가·삭제·일시정지·예산 설정은 만들지 않음 (그건 기존 /internal API 로).
권한은 EditorDep/AdminDep 가 세션(401) → CSRF(403) → 역할(403) 순서로 검사. 화면 버튼 숨김과 무관하게 서버가 막음.
"""
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.admin.deps import AdminDep, EditorDep, StoreDep, utcnow
from src.admin.read_router import to_admin_target
from src.admin.schemas import AdminTargetOut

router = APIRouter(prefix="/admin/api/targets", tags=["admin:write"])


class NoteIn(BaseModel):
    admin_note: str | None = Field(None, max_length=500)   # DB VARCHAR(500) 와 같은 한도 → DB 오류 대신 422


def budget_is_set(cfg: dict | None) -> bool:
    """monthly_budget_usd 가 0보다 큰 숫자일 때만 '설정됨'. 없음·null·0·문자열은 미설정 취급."""
    v = (cfg or {}).get("monthly_budget_usd")
    return isinstance(v, int | float) and not isinstance(v, bool) and v > 0


async def _load(store, target_id: int):
    found = await store.target_with_source(target_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "target not found")
    return found


@router.patch("/{target_id}/note", response_model=AdminTargetOut)
async def set_note(target_id: int, body: NoteIn, _: EditorDep, store: StoreDep):
    target, source = await _load(store, target_id)
    note = (body.admin_note or "").strip() or None      # 빈 문자열 = 메모 지움
    await store.set_note(target, note)
    return to_admin_target(target, source.name)


@router.post("/{target_id}/verify", response_model=AdminTargetOut)
async def verify(target_id: int, who: AdminDep, store: StoreDep):
    """X 대상 검증 → 스케줄러가 수집 시작. X API 는 유료라 소스 월 예산이 없으면 거부(409)."""
    target, source = await _load(store, target_id)
    if target.target_type != "x_account":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "only x_account targets can be verified here")
    if not budget_is_set(source.config):
        raise HTTPException(status.HTTP_409_CONFLICT, "monthly_budget_usd is not set for this source")
    await store.mark_verified(target, user_id=who.user_id, at=utcnow())
    return to_admin_target(target, source.name)

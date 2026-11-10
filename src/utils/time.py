from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """항상 tz-aware. naive datetime 을 DB에 넣지 않는다 (TIMESTAMPTZ 해석이 세션 tz에 따라 바뀜)."""
    return datetime.now(KST)


def ensure_kst(dt: datetime) -> datetime:
    """tz 없는 값은 KST로 간주 (국내 사이트 게시판 날짜), 있으면 KST로 변환."""
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)

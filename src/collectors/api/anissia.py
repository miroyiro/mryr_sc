"""애니시아 편성표 컬렉터 (준현). 규약: AnissiaCollector(source, client=None) · collect(target, params) · aclose().

흐름: 주차(0~8)별 편성표 → 정규화(parse_item) → (작품 × 앞으로 14일 방영일) CollectedItem
작품 매칭(anime_id)·이벤트 변환은 여기서 안 함 → process_service(name_matcher) · parsers/anissia_parser
"""
from datetime import date, datetime, timedelta

from src.collectors.base_api_collector import ApiError, BaseApiCollector
from src.collectors.types import CollectedItem, CollectResult
from src.models import ScrapeTarget
from src.utils.time import KST

BASE_URL = "https://api.anissia.net/anime/schedule"

# 작품 페이지 (event.source_url). animeNo 3463 = 바람의 저편 으로 사이트·API 대조 확정 (명주)
ANIME_PAGE_URL = "https://anissia.net/anime/{anime_no}"

SYNC_DAYS = 14


class AnissiaCollector(BaseApiCollector):
    source_name = "anissia"

    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        """POST /internal/anissia/sync {weeks?} 또는 스케줄(params 없음 → 0~8 전체)."""
        anime_list = await self.fetch_weeks((params or {}).get("weeks"))
        return CollectResult(items=self.to_items(anime_list, datetime.now(KST).date()))

    def to_items(self, anime_list: list[dict], today: date) -> list[CollectedItem]:
        """(작품 × 앞으로 14일 방영일) 하나 = raw_item 하나 = 방영 이벤트 하나.
        결방(status != ON) 제외. 같은 작품이 여러 주차에 나와도 같은 날짜는 한 번만."""
        items: dict[str, CollectedItem] = {}
        for item in anime_list:
            if item.get("status") != "ON":
                continue
            for broadcast_date in get_broadcast_dates(item, today):
                external_id = f"{item['anissia_no']}-{broadcast_date:%Y%m%d}"
                items.setdefault(external_id, CollectedItem(
                    external_id=external_id,
                    url=ANIME_PAGE_URL.format(anime_no=item["anissia_no"]),
                    title=item.get("title_ko"),
                    raw_data={**item, "broadcast_date": broadcast_date.isoformat()},
                ))
        return list(items.values())

    async def fetch_week(self, week: int):
        """애니시아 특정 주차 편성표 조회."""

        if week not in range(9):
            raise ValueError("week must be between 0 and 8")

        response = await self.get(
            f"{BASE_URL}/{week}"
        )

        # 실제 응답은 {"code": "ok", "data": [...]} (2026-11-24 확인). 공식 문서(2024-06)의 배열 단독 응답은 예전 형식
        # → 그 밖의 모양이면 실패 (조용히 0건으로 넘기면 편성표가 비어 보이기만 하고 아무도 모름)
        body = response.json()
        if not isinstance(body, dict) or body.get("code") != "ok" or not isinstance(body.get("data"), list):
            raise ApiError(f"anissia week {week}: unexpected response")

        return self.parse_items(
            body["data"],
            week,
        )

    async def fetch_weeks(
        self,
        weeks: list[int] | None = None,
    ):
        """요청한 주차의 편성표 조회."""

        if weeks is None:
            weeks = list(range(9))

        results = []

        for week in weeks:
            results.extend(
                await self.fetch_week(week)
            )

        return results

    def parse_items(self, items: list, week: int):
        return [
            self.parse_item(item, week)
            for item in items
        ]

    def parse_item(self, item: dict, week: int):
        """애니시아 응답을 내부 데이터 형식으로 정규화."""

        time_value = item.get("time")

        # 애니시아 0~6은 일요일~토요일
        # Python weekday는 월요일 0~일요일 6
        weekday = (week - 1) % 7 if week in range(7) else None

        return {
            "anissia_no": item["animeNo"],
            "status": item.get("status"),
            "title_ko": item.get("subject"),
            "original_title": item.get("originalSubject"),

            "genres": [
                genre.strip()
                for genre in (item.get("genres") or "").split(",")
                if genre.strip()
            ],

            "week": week,
            "broadcast_weekday": weekday,

            # 정규 요일일 때만 편성 시간 사용
            "broadcast_time": (
                time_value
                if weekday is not None
                else None
            ),

            # 7, 8은 일반 요일이 아닌 별도 주차
            "special_date": (
                time_value
                if week in (7, 8)
                else None
            ),

            "start_date": item.get("startDate"),
            "end_date": item.get("endDate"),
            "official_url": item.get("website"),
            "caption_count": item.get("captionCount"),

            # 작품 공식 X 주소 — 지금은 안 씀 (나중에 X 수집 대상 후보). thumbnail 은 저장 안 함 (이미지 규칙)
            **({"x_url": item["x"]} if item.get("x") else {}),
        }

def parse_date(value: str | None):
    """날짜 문자열을 date 객체로 변환."""

    if not value:
        return None

    value = str(value).strip()

    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(
                value,
                fmt,
            ).date()
        except ValueError:
            continue

    return None


def parse_time(value: str | None):
    """시간 문자열을 time 객체로 변환."""

    if not value:
        return None

    value = str(value).strip()

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(
                value,
                fmt,
            ).time()
        except ValueError:
            continue

    return None


def get_broadcast_dates(
    item: dict,
    today: date,
):
    """앞으로 14일 이내의 방영 날짜 계산."""

    result = []

    week = item["week"]

    start_date = parse_date(
        item.get("start_date")
    )

    end_date = parse_date(
        item.get("end_date")
    )

    target_end = today + timedelta(days=SYNC_DAYS - 1)

    # 방영 시작일이 14일 이후라면 제외
    if start_date and start_date > target_end:
        return result

    # 방영 종료일이 이미 지났다면 제외
    if end_date and end_date < today:
        return result

    # 0~6: 정규 요일 편성
    if week in range(7):

        weekday = item.get("broadcast_weekday")

        if weekday is None:
            return result

        for offset in range(SYNC_DAYS):

            broadcast_date = today + timedelta(days=offset)

            if broadcast_date.weekday() != weekday:
                continue

            if start_date and broadcast_date < start_date:
                continue

            if end_date and broadcast_date > end_date:
                continue

            result.append(broadcast_date)

    # 7, 8: 실제 날짜가 확인되는 경우만 처리
    elif week in (7, 8):

        special_date = parse_date(
            item.get("special_date")
        )

        if special_date is None:
            return result

        if today <= special_date <= target_end:
            result.append(special_date)

    return result


import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from rapidfuzz import fuzz

router = APIRouter(
    prefix="/internal/anissia",
    tags=["Anissia"],
)

BASE_URL = "https://api.anissia.net/anime/schedule"

KST = ZoneInfo("Asia/Seoul")

SYNC_DAYS = 14
MATCH_THRESHOLD = 85
MATCH_SCORE_GAP = 5

class AnissiaSyncRequest(BaseModel):
    weeks: list[int] | None = None

    @field_validator("weeks")
    @classmethod
    def validate_weeks(cls, value):
        if value is None:
            return value

        if not value:
            raise ValueError("weeks must not be empty")

        if any(week not in range(9) for week in value):
            raise ValueError("weeks must contain values from 0 to 8")

        if len(value) != len(set(value)):
            raise ValueError("weeks must not contain duplicates")

        return value


class UnmatchedAnime(BaseModel):
    anime_no: int
    subject: str


class AnissiaSyncResponse(BaseModel):
    synced_count: int
    new_anime_nos: list[int]
    broadcast_events_upserted: int
    unmatched: list[UnmatchedAnime]

class AnissiaCollector:

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Accept": "application/json",
            },
        )

    async def fetch_week(self, week: int):
        """애니시아 특정 주차 편성표 조회."""

        if week not in range(9):
            raise ValueError("week must be between 0 and 8")

        response = await self.client.get(
            f"{BASE_URL}/{week}"
        )

        response.raise_for_status()

        return self.parse_items(
            response.json(),
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
        }

    async def close(self):
        await self.client.aclose()

def normalize_title(title: str | None):
    """작품 제목 비교를 위한 문자열 정규화."""

    if not title:
        return ""

    title = title.lower().strip()

    # 공백과 특수문자 제거
    return re.sub(r"[\W_]+", "", title)


class AnissiaResolver:

    def __init__(self, candidates: list[dict]):
        # DB에서 한 번 조회한 후보 목록 재사용
        self.candidates = candidates

    def resolve(self, item: dict):
        """애니시아 작품과 AniList 작품 매칭."""

        source_titles = [
            normalize_title(item.get("title_ko")),
            normalize_title(item.get("original_title")),
        ]

        source_titles = [
            title for title in source_titles if title
        ]

        if not source_titles:
            return None

        scores = []

        for candidate in self.candidates:

            candidate_titles = [
                normalize_title(candidate.get("title_ko")),
                normalize_title(candidate.get("title_romaji")),
                normalize_title(candidate.get("title_english")),
                normalize_title(candidate.get("title_native")),
            ]

            candidate_titles = [
                title for title in candidate_titles if title
            ]

            if not candidate_titles:
                continue

            best_candidate_score = max(
                fuzz.ratio(source_title, candidate_title)
                for source_title in source_titles
                for candidate_title in candidate_titles
            )

            scores.append(
                (best_candidate_score, candidate)
            )

        if not scores:
            return None

        # 점수가 높은 후보부터 정렬
        scores.sort(
            key=lambda result: result[0],
            reverse=True,
        )

        best_score, best_candidate = scores[0]

        # 최소 유사도 미달이면 매칭하지 않음
        if best_score < MATCH_THRESHOLD:
            return None

        # 1위와 2위 점수가 너무 비슷하면 오매칭 방지
        if len(scores) > 1:
            second_score = scores[1][0]

            if best_score - second_score < MATCH_SCORE_GAP:
                return None

        return best_candidate

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

def get_anime_repository():
    raise NotImplementedError(
        "anime repository를 연결해야 합니다."
    )


def get_event_repository():
    raise NotImplementedError(
        "event repository를 연결해야 합니다."
    )

async def sync_anissia(
    weeks: list[int] | None,
    anime_repository,
    event_repository,
):
    """애니시아 방영 일정 동기화."""

    collector = AnissiaCollector()

    try:
        # 1. 애니시아 편성표 수집
        anime_list = await collector.fetch_weeks(weeks)

        # 2. AniList 작품 후보를 DB에서 한 번만 조회
        candidates = await (
            anime_repository.find_resolution_candidates()
        )

        resolver = AnissiaResolver(candidates)

        # 3. 동기화 결과 초기화
        synced_count = 0
        new_anime_nos = []
        broadcast_events_upserted = 0
        unmatched = []

        today = datetime.now(KST).date()

        # 같은 요청 내 중복 작품 처리 방지
        processed_anime_nos = set()

        # 4. 애니시아 작품 순회
        for item in anime_list:

            anime_no = item["anissia_no"]

            if anime_no in processed_anime_nos:
                continue

            processed_anime_nos.add(anime_no)

            # 5. AniList 작품 매칭
            matched = resolver.resolve(item)

            if matched is None:

                unmatched.append({
                    "anime_no": anime_no,
                    "subject": item.get("title_ko") or "",
                })

                continue

            anime_id = matched["anime_id"]

            # 6. anime 테이블 업데이트
            # 반환값:
            # True  = anissia_no가 처음 연결된 작품
            # False = 기존에 연결되어 있던 작품
            is_new = await (
                anime_repository.update_anissia_fields(
                    anime_id=anime_id,
                    title_ko=item.get("title_ko"),
                    anissia_no=anime_no,
                    broadcast_weekday=item.get("broadcast_weekday"),
                    broadcast_time=parse_time(
                        item.get("broadcast_time")
                    ),
                    official_url=item.get("official_url"),
                )
            )

            synced_count += 1

            if is_new:
                new_anime_nos.append(anime_no)

            # 7. 결방 작품은 이벤트 생성하지 않음
            if item.get("status") != "ON":
                continue

            # 8. 향후 14일 방영 날짜 계산
            broadcast_dates = get_broadcast_dates(
                item,
                today,
            )

            # 9. event 테이블 UPSERT
            for broadcast_date in broadcast_dates:

                source_id = (
                    f"{anime_no}-"
                    f"{broadcast_date.strftime('%Y%m%d')}"
                )

                event_data = {
                    "anime_id": anime_id,
                    "title": item.get("title_ko"),
                    "event_date": broadcast_date,
                    "type": "broadcast",
                    "source": "anissia",
                    "source_id": source_id,
                }

                await event_repository.upsert_broadcast_event(
                    event_data
                )

                broadcast_events_upserted += 1

        return {
            "synced_count": synced_count,
            "new_anime_nos": new_anime_nos,
            "broadcast_events_upserted": broadcast_events_upserted,
            "unmatched": unmatched,
        }

    finally:
        await collector.close()

@router.post(
    "/sync",
    response_model=AnissiaSyncResponse,
)
async def sync_anissia_endpoint(
    request: AnissiaSyncRequest,
    anime_repository=Depends(get_anime_repository),
    event_repository=Depends(get_event_repository),
):
    """POST /internal/anissia/sync"""

    try:
        result = await sync_anissia(
            weeks=request.weeks,
            anime_repository=anime_repository,
            event_repository=event_repository,
        )

        return result

    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Anissia API connection failed",
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

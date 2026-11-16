
import os
import asyncio
import xml.etree.ElementTree as ET

from datetime import date, datetime, timedelta

import httpx

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

router = APIRouter(
    prefix="/internal/kopis",
    tags=["KOPIS"],
)

BASE_URL = "http://www.kopis.or.kr/openApi/restful/pblprfr"

ROWS = 100

# 공연 조회 기간
PAST_DAYS = 30
FUTURE_DAYS = 365

# KOPIS 상세 조회 요청 간 대기 시간
REQUEST_DELAY = 0.2

class KopisSyncRequest(BaseModel):
    afterdate: str = Field(
        description="증분 수집 기준일 (YYYYMMDD)"
    )
    shcate: str | None = None

    @field_validator("afterdate")
    @classmethod
    def validate_afterdate(cls, value):
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            raise ValueError(
                "afterdate must be a valid YYYYMMDD date"
            )

        return value


class KopisSyncResponse(BaseModel):
    synced_count: int
    new_ids: list[str]

class KopisCollector:

    def __init__(self, api_key: str):
        self.api_key = api_key

        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Accept": "application/xml",
            },
        )

    async def fetch_list(
        self,
        stdate: str,
        eddate: str,
        afterdate: str | None = None,
        shcate: str | None = None,
        page: int = 1,
        rows: int = ROWS,
    ):
        """KOPIS 공연 목록 조회."""

        if rows < 1 or rows > 100:
            raise ValueError(
                "rows must be between 1 and 100"
            )

        if page < 1:
            raise ValueError("page must be greater than 0")

        # 날짜 형식 및 유효성 검사
        start = datetime.strptime(stdate, "%Y%m%d").date()
        end = datetime.strptime(eddate, "%Y%m%d").date()

        if start > end:
            raise ValueError(
                "stdate must be earlier than eddate"
            )

        # KOPIS 검색 기간을 31일 이내로 제한
        if (end - start).days > 30:
            raise ValueError(
                "date range must not exceed 31 days"
            )

        params = {
            "service": self.api_key,
            "stdate": stdate,
            "eddate": eddate,
            "cpage": page,
            "rows": rows,
        }

        if afterdate:
            params["afterdate"] = afterdate

        if shcate:
            params["shcate"] = shcate

        response = await self.client.get(
            BASE_URL,
            params=params,
        )

        response.raise_for_status()

        return self.parse_list(response.text)

    async def fetch_all(
        self,
        stdate: str,
        eddate: str,
        afterdate: str | None = None,
        shcate: str | None = None,
    ):
        """공연 목록 전체 페이지 조회."""

        results = []
        page = 1

        while True:
            items = await self.fetch_list(
                stdate=stdate,
                eddate=eddate,
                afterdate=afterdate,
                shcate=shcate,
                page=page,
                rows=ROWS,
            )

            results.extend(items)

            if len(items) < ROWS:
                break

            page += 1

        return results

    async def fetch_detail(self, mt20id: str):
        """KOPIS 공연 상세 정보 조회."""

        response = await self.client.get(
            f"{BASE_URL}/{mt20id}",
            params={
                "service": self.api_key,
            },
        )

        response.raise_for_status()

        return self.parse_detail(response.text)

    def parse_list(self, xml_text: str):
        """공연 목록 XML 파싱."""

        root = ET.fromstring(xml_text)

        return [
            {
                "mt20id": item.findtext("mt20id"),
                "title": item.findtext("prfnm"),
                "start_date": item.findtext("prfpdfrom"),
                "end_date": item.findtext("prfpdto"),
                "venue": item.findtext("fcltynm"),
                "poster_url": item.findtext("poster"),
                "area": item.findtext("area"),
                "genre_name": item.findtext("genrenm"),
                "performance_status": item.findtext("prfstate"),
            }
            for item in root.findall(".//db")
        ]

    def parse_detail(self, xml_text: str):
        """공연 상세 XML 파싱."""

        root = ET.fromstring(xml_text)

        item = root.find(".//db")

        if item is None:
            return None

        return {
            "mt20id": item.findtext("mt20id"),
            "title": item.findtext("prfnm"),
            "venue_id": item.findtext("mt10id"),
            "venue": item.findtext("fcltynm"),
            "start_date": item.findtext("prfpdfrom"),
            "end_date": item.findtext("prfpdto"),
            "first_registered_at": item.findtext("frstregdt"),
            "updated_at": item.findtext("updatedate"),
            "cast": item.findtext("prfcast"),
            "poster_url": item.findtext("poster"),
            "genre_name": item.findtext("genrenm"),
            "area": item.findtext("area"),
            "visit": item.findtext("visit"),
            "performance_status": item.findtext("prfstate"),
            "schedule": item.findtext("dtguidance"),
            "ticket_price": item.findtext("pcseguidance"),
            "booking_sites": self.parse_booking_sites(item),
        }

    def parse_booking_sites(self, item):
        """예매처 목록 파싱."""

        result = []

        # KOPIS XML의 relate 항목 조회
        bookings = item.findall(".//relate")

        for booking in bookings:
            result.append({
                "name": booking.findtext("relatenm"),
                "url": booking.findtext("relateurl"),
            })

        return result

    async def close(self):
        await self.client.aclose()

def get_search_periods():
    """KOPIS 조회 기간을 31일 단위로 분리."""

    today = date.today()

    start_date = today - timedelta(days=PAST_DAYS)
    end_date = today + timedelta(days=FUTURE_DAYS)

    periods = []

    current = start_date

    while current <= end_date:

        period_end = min(
            current + timedelta(days=30),
            end_date,
        )

        periods.append({
            "stdate": current.strftime("%Y%m%d"),
            "eddate": period_end.strftime("%Y%m%d"),
        })

        current = period_end + timedelta(days=1)

    return periods

def get_event_repository():
    raise NotImplementedError(
        "event repository를 연결해야 합니다."
    )


def get_artist_repository():
    raise NotImplementedError(
        "artist repository를 연결해야 합니다."
    )


def get_kopis_api_key():
    api_key = os.getenv("KOPIS_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KOPIS API key is not configured",
        )

    return api_key

async def sync_kopis(
    afterdate: str,
    shcate: str | None,
    api_key: str,
    event_repository,
    artist_repository,
):
    """KOPIS 내한 공연 증분 동기화."""

    collector = KopisCollector(api_key)

    try:
        periods = get_search_periods()

        performance_map = {}

        for period in periods:

            items = await collector.fetch_all(
                stdate=period["stdate"],
                eddate=period["eddate"],
                afterdate=afterdate,
                shcate=shcate,
            )

            # 날짜 구간 간 중복 공연 제거
            for item in items:
                mt20id = item.get("mt20id")

                if mt20id:
                    performance_map[mt20id] = item

        synced_count = 0
        new_ids = []

        for mt20id in performance_map:

            detail = await collector.fetch_detail(mt20id)

            if detail is None:
                continue

            # 내한 공연만 처리
            if detail.get("visit") != "Y":
                continue

            cast = detail.get("cast")

            artist_id = None

            if cast:
                artist = await artist_repository.find_kopis_artist(
                    cast
                )

                if artist is not None:
                    artist_id = artist["artist_id"]

            event_data = {
                "artist_id": artist_id,

                "title": detail["title"],
                "start_date": detail["start_date"],
                "end_date": detail["end_date"],

                "venue": detail["venue"],
                "venue_id": detail["venue_id"],

                "poster_url": detail["poster_url"],
                "area": detail["area"],

                "cast": cast,
                "genre_name": detail["genre_name"],

                "schedule": detail["schedule"],
                "ticket_price": detail["ticket_price"],
                "booking_sites": detail["booking_sites"],

                "category": "jpop",
                "type": "concert",

                "source": "kopis",
                "source_id": mt20id,

                "is_international": True,
            }

            is_new = await event_repository.upsert_kopis_event(
                event_data
            )

            synced_count += 1

            if is_new:
                new_ids.append(mt20id)

            # API 요청 간 대기
            await asyncio.sleep(REQUEST_DELAY)

        return {
            "synced_count": synced_count,
            "new_ids": new_ids,
        }

    finally:
        await collector.close()

@router.post(
    "/sync",
    response_model=KopisSyncResponse,
)
async def sync_kopis_endpoint(
    request: KopisSyncRequest,
    api_key: str = Depends(get_kopis_api_key),
    event_repository=Depends(get_event_repository),
    artist_repository=Depends(get_artist_repository),
):
    """POST /internal/kopis/sync"""

    try:
        result = await sync_kopis(
            afterdate=request.afterdate,
            shcate=request.shcate,
            api_key=api_key,
            event_repository=event_repository,
            artist_repository=artist_repository,
        )

        return result

    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="KOPIS API returned an error",
        )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="KOPIS API connection failed",
        )

    except ET.ParseError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="KOPIS XML parsing failed",
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        )

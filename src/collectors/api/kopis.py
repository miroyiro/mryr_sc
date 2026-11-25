"""KOPIS 공연 컬렉터 (준현). 규약: KopisCollector(source, client=None) · collect(target, params) · aclose().

흐름: 31일 구간별 목록(afterdate 증분, shcate 장르) → 상세 → visit=Y(내한)만 → CollectedItem
API 키: settings.KOPIS_API_KEY (SecretStr). URL 쿼리 service= 로 나가므로 실패 메시지는 base_api_collector 가 키 없이 만든다.
DB 저장·이벤트 변환은 여기서 안 함 → collect_service(raw_item) · parsers/kopis_parser(event)
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from src.collectors.base_api_collector import ApiError, BaseApiCollector
from src.collectors.types import CollectedItem, CollectResult
from src.config.settings import settings
from src.models import ScrapeTarget
from src.utils.time import KST

BASE_URL = "http://www.kopis.or.kr/openApi/restful/pblprfr"
# 사람이 보는 공연 상세 페이지 (event.source_url) — 형식 확인 필요
DETAIL_PAGE_URL = "https://www.kopis.or.kr/por/db/pblprfr/pblprfrView.do?menuId=MNU_00020&mt20Id={mt20id}"

ROWS = 100

# 공연 조회 기간
PAST_DAYS = 30
FUTURE_DAYS = 365

# params 없이(스케줄) 돌 때 기본값: 최근 7일 갱신분 · 대중음악만 (전 장르 전체면 상세 호출이 수천 번)
DEFAULT_AFTERDATE_DAYS = 7
DEFAULT_SHCATE = "CCCD"   # 대중음악 — 코드 확인 필요


class KopisCollector(BaseApiCollector):
    source_name = "kopis"
    accept = "application/xml"

    @property
    def api_key(self) -> str:
        if settings.KOPIS_API_KEY is None or not settings.KOPIS_API_KEY.get_secret_value():
            raise ApiError("KOPIS_API_KEY not set")
        return settings.KOPIS_API_KEY.get_secret_value()

    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        """POST /internal/kopis/sync {afterdate?, shcate?} 또는 스케줄(params 없음)."""
        params = params or {}
        afterdate = params.get("afterdate") or (
            datetime.now(KST).date() - timedelta(days=DEFAULT_AFTERDATE_DAYS)
        ).strftime("%Y%m%d")
        shcate = params.get("shcate") or DEFAULT_SHCATE

        # 날짜 구간 간 중복 공연 제거
        performance_map: dict[str, dict] = {}
        for period in get_search_periods():
            for item in await self.fetch_all(stdate=period["stdate"], eddate=period["eddate"],
                                             afterdate=afterdate, shcate=shcate):
                if item.get("mt20id"):
                    performance_map[item["mt20id"]] = item

        details = []
        for mt20id in performance_map:
            detail = await self.fetch_detail(mt20id)
            # 내한 공연만
            if detail is not None and detail.get("visit") == "Y":
                details.append(detail)

        return CollectResult(items=[self.to_item(d) for d in details])

    def to_item(self, detail: dict) -> CollectedItem:
        """상세 1건 → raw_item 1건. 포스터는 raw_data 에만 (images 저장 X). 날짜·장소 해석은 kopis_parser."""
        return CollectedItem(
            external_id=detail["mt20id"],
            url=DETAIL_PAGE_URL.format(mt20id=detail["mt20id"]),
            title=detail.get("title"),
            published_at=_parse_updated(detail.get("updated_at")),
            raw_data=detail,
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

        response = await self.get(
            BASE_URL,
            params=params,
        )

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

        response = await self.get(
            f"{BASE_URL}/{mt20id}",
            params={
                "service": self.api_key,
            },
        )

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

def get_search_periods():
    """KOPIS 조회 기간을 31일 단위로 분리."""

    today = datetime.now(KST).date()

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


def _parse_updated(value: str | None) -> datetime | None:
    """updatedate '2026-11-24 15:00:03.04272'(소수 초 자릿수 일정치 않음, 2026-11-24 실제 응답) → KST datetime.
    바뀌면 raw_item hash 가 달라져 재가공됨."""
    try:
        return datetime.fromisoformat(value.strip()).replace(tzinfo=KST) if value else None
    except ValueError:
        return None

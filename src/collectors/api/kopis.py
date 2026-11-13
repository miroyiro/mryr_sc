
import xml.etree.ElementTree as ET
import httpx


class KopisCollector:
    BASE_URL = "http://www.kopis.or.kr/openApi/restful/pblprfr"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def fetch_list(
        self,
        stdate: str,
        eddate: str,
        afterdate: str | None = None,
        shcate: str | None = None,
        page: int = 1,
        rows: int = 100,
    ):
        """KOPIS 공연 목록 조회."""
        if rows < 1 or rows > 100:
            raise ValueError("rows must be between 1 and 100")

        if len(stdate) != 8 or len(eddate) != 8:
            raise ValueError("stdate and eddate must be YYYYMMDD")

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
            self.BASE_URL,
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
        """전체 페이지의 공연 목록 조회."""
        results = []
        page = 1
        rows = 100

        while True:
            items = await self.fetch_list(
                stdate=stdate,
                eddate=eddate,
                afterdate=afterdate,
                shcate=shcate,
                page=page,
                rows=rows,
            )

            results.extend(items)

            if len(items) < rows:
                break

            page += 1

        return results

    async def fetch_detail(self, mt20id: str):
        """공연 상세 조회."""
        response = await self.client.get(
            f"{self.BASE_URL}/{mt20id}",
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

        for booking in item.findall(".//relates"):
            result.append({
                "name": booking.findtext("relatenm"),
                "url": booking.findtext("relateurl"),
            })

        return result

    async def close(self):
        await self.client.aclose()

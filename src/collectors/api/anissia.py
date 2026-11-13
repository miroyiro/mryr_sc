
import asyncio
import httpx


class AnissiaCollector:
    BASE_URL = "https://api.anissia.net/anime/schedule"

    WEEKDAYS = {
        0: 6,  # 일요일: Python weekday
        1: 0,  # 월요일
        2: 1,
        3: 2,
        4: 3,
        5: 4,
        6: 5,  # 토요일
    }

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def fetch_week(self, week: int):
        """애니시아 주차별 편성표 조회."""
        if week not in range(9):
            raise ValueError("week must be between 0 and 8")

        response = await self.client.get(
            f"{self.BASE_URL}/{week}"
        )

        response.raise_for_status()

        return self.parse_items(
            response.json(),
            week,
        )

    async def fetch_weeks(self, weeks: list[int] | None = None):
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
        """공식 응답 필드 기반 정규화."""
        weekday = self.WEEKDAYS.get(week)

        time_value = item.get("time")

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
            "broadcast_weekday": (week - 1) % 7,
            "broadcast_time": (
                time_value
                if weekday is not None
                else None
            ),
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

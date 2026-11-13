
import asyncio
from datetime import timedelta

import httpx


class AniListCollector:
    BASE_URL = "https://graphql.anilist.co"

    SEASON_QUERY = """
    query ($season: MediaSeason!, $seasonYear: Int!, $page: Int!) {
        Page(page: $page, perPage: 50) {
            pageInfo {
                hasNextPage
            }
            media(
                season: $season
                seasonYear: $seasonYear
                type: ANIME
                isAdult: false
                sort: POPULARITY_DESC
            ) {
                id
            }
        }
    }
    """

    DETAIL_FIELDS = """
        id
        title {
            romaji
            english
            native
        }
        season
        seasonYear
        episodes
        status
        coverImage {
            large
            extraLarge
        }
        studios {
            nodes {
                id
                name
            }
        }
        staff(page: 1, perPage: 25) {
            edges {
                role
                node {
                    id
                    name {
                        full
                    }
                }
            }
        }
        characters(page: 1, perPage: 50) {
            edges {
                role
                node {
                    id
                    name {
                        full
                    }
                }
                voiceActors(language: JAPANESE, page: 1, perPage: 10) {
                    id
                    name {
                        full
                    }
                    languageV2
                }
            }
        }
    """

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def request(self, query: str, variables: dict | None = None):
        """AniList GraphQL 요청 및 오류 처리."""
        response = await self.client.post(
            self.BASE_URL,
            json={
                "query": query,
                "variables": variables or {},
            },
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise RuntimeError(
                f"ANILIST_RATE_LIMIT:{retry_after}"
            )

        response.raise_for_status()

        body = response.json()

        if body.get("errors"):
            raise RuntimeError(
                f"ANILIST_GRAPHQL_ERROR: {body['errors']}"
            )

        remaining = response.headers.get(
            "X-RateLimit-Remaining"
        )

        return body["data"], (
            int(remaining) if remaining is not None else None
        )

    async def fetch_season_ids(
        self,
        season: str,
        season_year: int,
    ) -> list[int]:
        """분기별 애니메이션 ID 목록 조회."""
        season = season.upper()
        page = 1
        anime_ids = []

        while True:
            data, _ = await self.request(
                self.SEASON_QUERY,
                {
                    "season": season,
                    "seasonYear": season_year,
                    "page": page,
                },
            )

            page_data = data["Page"]

            anime_ids.extend(
                item["id"]
                for item in page_data["media"]
            )

            if not page_data["pageInfo"]["hasNextPage"]:
                break

            page += 1
            await asyncio.sleep(2)

        return anime_ids

    async def fetch_anime_batch(
        self,
        anime_ids: list[int],
    ):
        """여러 작품을 GraphQL alias로 묶어서 조회."""
        if not anime_ids:
            return [], None

        aliases = []

        for index, anime_id in enumerate(anime_ids):
            aliases.append(
                f"""
                anime_{index}: Media(
                    id: {int(anime_id)}
                    type: ANIME
                ) {{
                    {self.DETAIL_FIELDS}
                }}
                """
            )

        query = "query { " + "\n".join(aliases) + " }"

        data, remaining = await self.request(query)

        results = []

        for index in range(len(anime_ids)):
            item = data.get(f"anime_{index}")

            if item is not None:
                results.append(self.parse_anime(item))

        return results, remaining

    def parse_anime(self, item: dict):
        """AniList 응답을 내부 데이터로 정규화."""
        cover = item.get("coverImage") or {}

        return {
            "anilist_id": item["id"],
            "title_romaji": (item.get("title") or {}).get("romaji"),
            "title_english": (item.get("title") or {}).get("english"),
            "title_native": (item.get("title") or {}).get("native"),
            "season": item.get("season"),
            "season_year": item.get("seasonYear"),
            "episodes": item.get("episodes"),
            "status": item.get("status"),
            "poster_url": (
                cover.get("extraLarge")
                or cover.get("large")
            ),
            "studios": [
                {
                    "id": studio["id"],
                    "name": studio["name"],
                }
                for studio in (
                    item.get("studios") or {}
                ).get("nodes", [])
            ],
            "staff": [
                {
                    "id": edge["node"]["id"],
                    "name": edge["node"]["name"]["full"],
                    "role": edge.get("role"),
                }
                for edge in (
                    item.get("staff") or {}
                ).get("edges", [])
            ],
            "characters": [
                {
                    "id": edge["node"]["id"],
                    "name": edge["node"]["name"]["full"],
                    "role": edge.get("role"),
                    "voice_actors": [
                        {
                            "id": actor["id"],
                            "name": actor["name"]["full"],
                            "language": actor.get("languageV2"),
                        }
                        for actor in edge.get("voiceActors", [])
                    ],
                }
                for edge in (
                    item.get("characters") or {}
                ).get("edges", [])
            ],
        }

    async def sync_season(self, season: str, season_year: int):
        """분기 작품 ID 조회 후 alias 배치 상세 수집."""
        anime_ids = await self.fetch_season_ids(
            season,
            season_year,
        )

        results = []
        rate_limit_remaining = None

        batch_size = 10

        for index in range(0, len(anime_ids), batch_size):
            batch = anime_ids[index:index + batch_size]

            items, remaining = await self.fetch_anime_batch(
                batch
            )

            results.extend(items)

            if remaining is not None:
                rate_limit_remaining = remaining

            if index + batch_size < len(anime_ids):
                await asyncio.sleep(2)

        return {
            "anime_ids": anime_ids,
            "items": results,
            "rate_limit_remaining": rate_limit_remaining,
        }

    async def close(self):
        await self.client.aclose()



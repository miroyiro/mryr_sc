
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter(
    prefix="/internal/anilist",
    tags=["AniList"],
)

BASE_URL = "https://graphql.anilist.co"

BATCH_SIZE = 10
REQUEST_DELAY = 2

SEASON_TTL = timedelta(days=1)
FINISHED_TTL = timedelta(days=30)

class AniListSyncRequest(BaseModel):
    season: Literal["winter", "spring", "summer", "fall"]
    season_year: int = Field(ge=1900, le=2100)


class AniListSyncResponse(BaseModel):
    synced_count: int
    new_anilist_ids: list[int]
    rate_limit_remaining: int | None

class AniListCollector:

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
                status
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

    async def request(
        self,
        query: str,
        variables: dict | None = None,
    ):
        """AniList GraphQL 요청 및 오류 처리."""

        response = await self.client.post(
            BASE_URL,
            json={
                "query": query,
                "variables": variables or {},
            },
        )

        if response.status_code == 429:
            retry_after = response.headers.get(
                "Retry-After",
                "60",
            )

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
    ) -> list[dict]:
        """분기별 작품 ID와 방영 상태 조회."""

        page = 1
        anime_list = []

        while True:
            data, _ = await self.request(
                self.SEASON_QUERY,
                {
                    "season": season.upper(),
                    "seasonYear": season_year,
                    "page": page,
                },
            )

            page_data = data["Page"]

            anime_list.extend(
                {
                    "anilist_id": item["id"],
                    "status": item["status"],
                }
                for item in page_data["media"]
            )

            if not page_data["pageInfo"]["hasNextPage"]:
                break

            page += 1
            await asyncio.sleep(REQUEST_DELAY)

        return anime_list

    async def fetch_anime_batch(
        self,
        anime_ids: list[int],
    ):
        """GraphQL alias로 여러 작품 상세 정보 조회."""

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
        """AniList 원본 응답을 내부 데이터로 변환."""

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

    async def close(self):
        await self.client.aclose()

def select_sync_targets(
    anime_list: list[dict],
    existing_anime: list[dict],
):
    """방영 상태, 팔로우 여부, TTL 기준으로 대상 선별."""

    existing_map = {
        item["anilist_id"]: item
        for item in existing_anime
    }

    now = datetime.now(timezone.utc)

    target_ids = []

    for item in anime_list:
        anilist_id = item["anilist_id"]
        anime_status = item["status"]

        existing = existing_map.get(anilist_id)

        is_followed = (
            existing["is_followed"]
            if existing
            else False
        )

        # 방영 중이거나 팔로우된 작품만 대상
        if anime_status != "RELEASING" and not is_followed:
            continue

        # 상태별 TTL
        if anime_status == "RELEASING":
            ttl = SEASON_TTL
        elif anime_status == "FINISHED":
            ttl = FINISHED_TTL
        else:
            continue

        # 신규 작품
        if existing is None:
            target_ids.append(anilist_id)
            continue

        synced_at = existing["synced_at"]

        if synced_at is None:
            target_ids.append(anilist_id)
            continue

        # DB 시간이 timezone 없는 datetime일 경우 보정
        if synced_at.tzinfo is None:
            synced_at = synced_at.replace(
                tzinfo=timezone.utc
            )

        if now - synced_at >= ttl:
            target_ids.append(anilist_id)

    return target_ids

def get_anime_repository():
    raise NotImplementedError(
        "프로젝트의 anime repository를 연결해야 합니다."
    )

def get_anime_character_repository():
    raise NotImplementedError(
        "프로젝트의 anime_character repository를 연결해야 합니다."
    )

async def sync_anilist(
    season: str,
    season_year: int,
    anime_repository,
    anime_character_repository,
):
    """분기별 애니메이션 카탈로그 동기화."""

    collector = AniListCollector()

    try:
        # 1. 분기별 작품 ID 및 상태 조회
        anime_list = await collector.fetch_season_ids(
            season,
            season_year,
        )

        anilist_ids = [
            item["anilist_id"]
            for item in anime_list
        ]

        # 2. DB 기존 작품 정보 조회
        existing_anime = (
            await anime_repository.find_sync_candidates(
                anilist_ids
            )
        )

        # 3. 동기화 대상 선별
        target_ids = select_sync_targets(
            anime_list,
            existing_anime,
        )

        # 4. 대상 작품 상세 수집
        results = []
        rate_limit_remaining = None

        for index in range(0, len(target_ids), BATCH_SIZE):
            batch = target_ids[index:index + BATCH_SIZE]

            items, remaining = await collector.fetch_anime_batch(
                batch
            )

            results.extend(items)

            if remaining is not None:
                rate_limit_remaining = remaining

            if index + BATCH_SIZE < len(target_ids):
                await asyncio.sleep(REQUEST_DELAY)

        # 5. DB UPSERT
        new_anilist_ids = []

        for item in results:
            anilist_id = item["anilist_id"]

            is_new = await anime_repository.upsert_anime(
                item
            )

            if is_new:
                new_anilist_ids.append(anilist_id)

            await anime_character_repository.upsert_characters(
                anilist_id,
                item["characters"],
            )

        # 6. 결과 반환
        return {
            "synced_count": len(results),
            "new_anilist_ids": new_anilist_ids,
            "rate_limit_remaining": rate_limit_remaining,
        }

    finally:
        await collector.close()

@router.post(
    "/sync",
    response_model=AniListSyncResponse,
)
async def sync_anilist_endpoint(
    request: AniListSyncRequest,
    anime_repository=Depends(get_anime_repository),
    anime_character_repository=Depends(
        get_anime_character_repository
    ),
):
    """POST /internal/anilist/sync"""

    try:
        result = await sync_anilist(
            season=request.season,
            season_year=request.season_year,
            anime_repository=anime_repository,
            anime_character_repository=anime_character_repository,
        )

        return result

    except RuntimeError as error:
        message = str(error)

        if message.startswith("ANILIST_RATE_LIMIT"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AniList rate limit exceeded",
            )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AniList GraphQL request failed",
        )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AniList API connection failed",
        )

"""AniList GraphQL 클라이언트. 수집(registry)이 아니라 services/anilist_resolver.py 가 직접 쓴다.

- aclose(): 자기가 만든 httpx 클라이언트만 닫는다 (넘겨받은 건 호출한 쪽 책임)
- 429·5xx·연결 오류는 재시도 (Retry-After 존중), 4xx 는 바로 실패. 끝까지 429 면 AniListRateLimited
- 응답 필드명(format·genres·description·synonyms 포함)·쿼리 복잡도 한도는 실응답으로 미검증 → .get() 으로 읽음
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from src.collectors.scraping.base_scraper import _retry_after_sec
from src.config.settings import settings

BASE_URL = "https://graphql.anilist.co"

BATCH_SIZE = 10
REQUEST_DELAY = 2

SEASON_TTL = timedelta(days=1)
FINISHED_TTL = timedelta(days=30)

_sleep = asyncio.sleep   # 테스트에서 바꿔 끼워 대기를 0으로


class AniListError(Exception):
    """AniList 호출 실패. status = HTTP 상태 (연결 오류·형식 오류면 None)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AniListRateLimited(AniListError):
    """429 가 재시도 끝까지 이어짐. retry_after = 응답 Retry-After 초 (없으면 60)."""

    def __init__(self, retry_after: int):
        super().__init__(f"anilist rate limited, retry after {retry_after}s", 429)
        self.retry_after = retry_after


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
        format
        genres
        description
        synonyms
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

    # 검색용: 리졸버(_score·to_anime_payload)가 읽는 필드만. staff·characters 는 빼서 쿼리 복잡도를 낮춤 (한도 미검증)
    SEARCH_FIELDS = """
        id
        title { romaji english native }
        synonyms
        format
        status
        season
        seasonYear
        episodes
        genres
        description
        coverImage { large extraLarge }
        studios { nodes { id name } }
    """

    SEARCH_QUERY = (
        "query ($search: String!, $perPage: Int!) {"
        " Page(page: 1, perPage: $perPage) {"
        " media(search: $search, type: ANIME, isAdult: false) {" + SEARCH_FIELDS + "} } }"
    )

    def __init__(self, client: httpx.AsyncClient | None = None):
        # 넘겨받은 client 는 닫지 않는다 (테스트 MockTransport·공유 클라이언트용)
        self._own_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        """자기가 만든 클라이언트만 닫음 → 호출마다 만든 연결이 새지 않게."""
        if self._own_client:
            await self.client.aclose()

    async def request(
        self,
        query: str,
        variables: dict | None = None,
    ):
        """AniList GraphQL 요청. 429·5xx·연결 오류는 재시도, 4xx·형식 오류는 바로 AniListError."""

        last: AniListError | None = None
        for attempt in range(1, settings.HTTP_MAX_RETRIES + 1):
            is_last = attempt == settings.HTTP_MAX_RETRIES
            try:
                response = await self.client.post(
                    BASE_URL,
                    json={
                        "query": query,
                        "variables": variables or {},
                    },
                )
            except httpx.TransportError as exc:
                last = AniListError(f"anilist POST → {type(exc).__name__}")
                if not is_last:
                    await _sleep(2 ** attempt)
                continue

            if response.status_code == 429:
                retry_after = _retry_after_sec(response)
                last = AniListRateLimited(int(retry_after) if retry_after is not None else 60)
                if not is_last:
                    await _sleep(retry_after or 2 ** attempt)
                continue
            if response.status_code >= 500:
                last = AniListError(f"anilist POST → {response.status_code}", response.status_code)
                if not is_last:
                    await _sleep(_retry_after_sec(response) or 2 ** attempt)
                continue
            if response.status_code >= 400:
                raise AniListError(f"anilist POST → {response.status_code}", response.status_code)

            try:
                body = response.json()
            except ValueError:
                raise AniListError("anilist: response is not JSON") from None

            if isinstance(body, dict) and body.get("errors"):
                raise AniListError(f"anilist graphql error: {body['errors']}")
            # 빈 응답·형식 변경 → KeyError 대신 원인이 보이는 실패
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict):
                raise AniListError("anilist: response has no data")

            remaining = response.headers.get(
                "X-RateLimit-Remaining"
            )

            return data, (
                int(remaining) if remaining is not None and remaining.isdigit() else None
            )

        assert last is not None
        raise last

    async def search_media(self, title: str, *, per_page: int = 5) -> list[dict]:
        """제목 검색 → AniList 원본 media 리스트 (리졸버가 점수 매김). 0건은 [] (정상)."""
        data, _ = await self.request(self.SEARCH_QUERY, {"search": title, "perPage": per_page})
        page = data.get("Page")
        if not isinstance(page, dict):
            raise AniListError("anilist search: response has no Page")
        # id 없는 항목은 to_anime_payload(media["id"]) 에서 터지므로 버림
        return [m for m in (page.get("media") or []) if isinstance(m, dict) and m.get("id")]

    async def fetch_media_batch(self, anime_ids: list[int]) -> dict[int, dict]:
        """여러 id 를 alias 로 BATCH_SIZE 씩 조회 → {id: 원본 media}. 없는 id(null alias)는 빠짐.
        한 번에 수십 개를 보내 쿼리 복잡도 한도에 걸리는 걸 막으려고 나눔 (한도 수치 미검증).
        없는 id 를 섞으면 AniList 가 null+200 인지 404 인지 미검증 — 404 면 그 배치 전체가 AniListError."""
        out: dict[int, dict] = {}
        for start in range(0, len(anime_ids), BATCH_SIZE):
            if start:
                await _sleep(REQUEST_DELAY)
            batch = anime_ids[start:start + BATCH_SIZE]
            aliases = "\n".join(
                f"m{i}: Media(id: {int(anime_id)}, type: ANIME) {{ {self.DETAIL_FIELDS} }}"
                for i, anime_id in enumerate(batch)
            )
            data, _ = await self.request("query { " + aliases + " }")
            for i in range(len(batch)):
                media = data.get(f"m{i}")
                if isinstance(media, dict) and media.get("id"):
                    out[media["id"]] = media
        return out

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
                    "id": item["id"],          # 리졸버 sync_season 이 m["id"] 로 읽음
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

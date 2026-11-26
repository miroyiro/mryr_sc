"""TMDB 공식 provider 목록(KR)과 tmdb.PROVIDER_PLATFORM·NAME_PLATFORM 대조 (수동 실행용, 테스트에서 안 돌림).

무엇: GET /watch/providers/tv?watch_region=KR 를 1회 호출해 우리 매핑의 id·이름이 실제와 맞는지 출력.
막는 것: PROVIDER_PLATFORM 의 미검증 id 가 틀려 스트리밍이 other_providers 로 빠지거나 엉뚱한 플랫폼에 붙는 것.

실행:  python -m scripts.tmdb_provider_check   (TMDB_API_KEY 필요. 키는 출력하지 않음)
"""
import sys

import httpx

from src.collectors.api.tmdb import API_BASE, NAME_PLATFORM, PROVIDER_PLATFORM
from src.config.settings import settings


def main() -> int:
    key = settings.TMDB_API_KEY.get_secret_value() if settings.TMDB_API_KEY else ""
    if not key:
        print("TMDB_API_KEY not set")
        return 1
    headers, params = {}, {"watch_region": "KR", "language": "ko-KR"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    resp = httpx.get(f"{API_BASE}/watch/providers/tv", params=params, headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"HTTP {resp.status_code}")   # URL 은 출력하지 않음 (api_key 포함)
        return 1
    official = {p["provider_id"]: p.get("provider_name", "") for p in resp.json().get("results") or []}

    print("== PROVIDER_PLATFORM 대조 ==")
    for pid, platform in PROVIDER_PLATFORM.items():
        name = official.get(pid)
        print(f"{'OK ' if name else 'NG '} {pid:>6} → {platform:<14} 공식 이름: {name or '(KR 목록에 없음)'}")

    print("\n== 이름 보조 매핑 후보 (공식 목록 중 NAME_PLATFORM 에 걸리는 것) ==")
    for pid, name in sorted(official.items()):
        platform = NAME_PLATFORM.get(name.casefold())
        if platform and PROVIDER_PLATFORM.get(pid) != platform:
            print(f"   {pid:>6} {name!r} → {platform}  (PROVIDER_PLATFORM 에 없음/다름)")

    print(f"\n공식 KR provider {len(official)}개 전체:")
    for pid, name in sorted(official.items()):
        print(f"   {pid:>6} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

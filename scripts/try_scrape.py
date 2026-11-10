"""DB·backend 없이 실제 사이트를 한 번 긁어서 '어떤 데이터가 오는지' + 파싱 결과를 출력 (명주).

  python -m scripts.try_scrape animate            # 목록 + 새 글 상세 3개 (10초 간격 → 약 40초)
  python -m scripts.try_scrape aniplus-news
  python -m scripts.try_scrape laftel --limit 5    # 사이트맵 + 작품 5개 (1.5초 간격)
  python -m scripts.try_scrape simulcast --season fall --year 2026   # playwright install chromium 필요
  옵션 --json : raw_item 모양(JSON) 그대로 출력

robots.txt·간격·UA 는 실제 컬렉터 코드 그대로 씀 (BaseScraper). 저장은 안 함.
"""
import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace

from src.config.settings import settings

SOURCES = {
    # name: (scrape_source.name, base_url, delay_ms, target_value)
    "animate": ("animate", "https://www.animate-onlineshop.co.kr", 10_000,
                "https://www.animate-onlineshop.co.kr/board/list.php?bdId=event&period=all"),
    "aniplus-news": ("aniplus", "https://news.aniplustv.com", 3000, "https://news.aniplustv.com/news-sitemap.xml"),
    "simulcast": ("aniplus", "https://www.aniplustv.com", 3000, "https://www.aniplustv.com/list"),
    "laftel": ("laftel", "https://laftel.net", 1500, "https://laftel.net/sitemaps/items.xml"),
}


def _source(key: str, extra: dict):
    name, base, delay, _ = SOURCES[key]
    cfg = {"delay_ms": delay, **extra}
    return SimpleNamespace(name=f"try-{key}", base_url=base, config=cfg, cfg=lambda k, d=None: cfg.get(k, d))


def _default(o):
    return o.isoformat() if isinstance(o, datetime) else str(o)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", choices=list(SOURCES))
    ap.add_argument("--limit", type=int, default=3, help="animate 상세 / laftel 작품 수")
    ap.add_argument("--last-seen", default=None, help="증분 기준 (animate 게시글 번호, laftel id …)")
    ap.add_argument("--season", default=None)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    target = SimpleNamespace(value=SOURCES[args.source][3], last_seen_external_id=args.last_seen,
                             anime_id=None, artist_id=None)
    params = {}
    if args.source == "animate":
        from src.collectors.scraping.animate import AnimateEventCollector as cls
        params = {"max_detail": args.limit}
        if args.last_seen is None:   # 처음이면 최신 limit 개만 보기
            target.last_seen_external_id = "__latest__"
    elif args.source == "aniplus-news":
        from src.collectors.scraping.aniplus import AniplusNewsCollector as cls
    elif args.source == "laftel":
        from src.collectors.scraping.laftel import LaftelSitemapCollector as cls
        params = {"batch_size": args.limit}
    else:
        from src.collectors.scraping.aniplus_simulcast import AniplusSimulcastCollector as cls
        settings.PLAYWRIGHT_ENABLED = True
        params = {"season": args.season, "season_year": args.year}

    collector = cls(_source(args.source, {}))
    try:
        if target.last_seen_external_id == "__latest__":
            # 목록만 먼저 받아서 '최신 N개 직전 번호'를 커서로 → 상세는 N개만
            from src.collectors.scraping.animate import parse_list
            rows = parse_list((await collector.fetch(target.value)).text)
            nums = sorted(int(r.external_id) for r in rows)
            target.last_seen_external_id = str(nums[-args.limit - 1]) if len(nums) > args.limit else "0"
        result = await collector.collect(target, params=params)
    finally:
        await collector.aclose()

    print(f"# {args.source}: {len(result.items)}건, next cursor = {result.last_seen_external_id}\n")
    for item in result.items:
        if args.json:
            print(json.dumps(asdict(item), ensure_ascii=False, default=_default, indent=2))
            continue
        print(f"- [{item.external_id}] {item.title}\n  {item.url}  published={item.published_at}")
        print(f"  raw_data={json.dumps(item.raw_data, ensure_ascii=False, default=_default)}")

    if args.source == "animate":   # 가공 결과(processed_item / main.event payload)까지 보기
        from src.parsers.animate_parser import AnimateEventParser
        print("\n# 파싱 결과 (processed_item.event_data)")
        for item in result.items:
            raw = SimpleNamespace(title=item.title, content=None, url=item.url, external_id=item.external_id,
                                  raw_data=item.raw_data)
            parsed = AnimateEventParser().parse(raw, source_name="animate")
            print(json.dumps(parsed.to_values(), ensure_ascii=False, default=_default, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

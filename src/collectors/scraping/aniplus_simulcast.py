"""애니플러스 TV 한일 동시방영 목록 — SPA 렌더링 (명주). 분기 1회 (+ X 공지로 보정).

페이지 : https://www.aniplustv.com/list   (robots 전부 허용, 2026-11-10 확인)
구조   : 분기 체크박스 <label for="checkbox_{YYYY}{MM}">2026년 4분기</label>  (MM = 01/04/07/10)
         카드 <div class="div_li"> … <div class="title"><p>템빨 ~아이템의 힘~ (더빙)</p></div></div>
         카드에 작품별 링크 없음 → url 은 목록 페이지
         같은 작품이 (더빙)/(자막) 두 장으로 나옴 → base_title 로 묶어서 매칭
Playwright(Chromium) 필요 → 미니PC에서만, settings.PLAYWRIGHT_ENABLED=True 일 때만

params: {"season": "fall", "season_year": 2026}  (없으면 현재 분기)
target: target_type='spa_page', value='https://www.aniplustv.com/list'
결과 용도: catalog_service → anime_streaming(platform=aniplus_tv, source=aniplus)
"""
import re

from src.collectors.scraping.base_scraper import BaseScraper, LayoutChanged
from src.collectors.types import CollectedItem, CollectResult
from src.config.settings import settings
from src.models import ScrapeTarget
from src.utils.time import now_kst

SELECTORS = {
    "card": "div.div_li",
    "title": ".title p",
    "season_label": 'label[for="checkbox_{ym}"]',
}
SEASON_MONTH = {"winter": 1, "spring": 4, "summer": 7, "fall": 10}
VERSION_RE = re.compile(r"\s*\((더빙|자막)\)\s*$")


def season_key(season: str | None, year: int | None) -> tuple[str, int, str]:
    """→ (season, year, 'YYYYMM'). 없으면 오늘 기준 분기."""
    if not season or not year:
        now = now_kst()
        month = ((now.month - 1) // 3) * 3 + 1
        season = {v: k for k, v in SEASON_MONTH.items()}[month]
        year = now.year
    season = season.lower()
    if season not in SEASON_MONTH:
        raise ValueError(f"season must be one of {list(SEASON_MONTH)}")
    return season, int(year), f"{int(year)}{SEASON_MONTH[season]:02d}"


def split_version(title: str) -> tuple[str, str | None]:
    m = VERSION_RE.search(title)
    if not m:
        return title.strip(), None
    return VERSION_RE.sub("", title).strip(), {"더빙": "dub", "자막": "sub"}[m[1]]


def build_items(titles: list[str], *, url: str, season: str, year: int) -> list[CollectedItem]:
    out: list[CollectedItem] = []
    seen: set[str] = set()
    for raw in titles:
        title = " ".join((raw or "").split())
        if not title or title in seen:
            continue
        seen.add(title)
        base, version = split_version(title)
        out.append(CollectedItem(
            external_id=f"{year}{SEASON_MONTH[season]:02d}:{title}"[:100],
            url=url,
            title=title[:300],
            raw_data={"base_title": base, "version": version, "season": season, "season_year": year,
                      "platform": "aniplus_tv"},
        ))
    return out


class AniplusSimulcastCollector(BaseScraper):
    source_name = "aniplus"
    store_content = False
    default_delay_ms = 3000

    async def collect(self, target: ScrapeTarget | None, params: dict | None = None) -> CollectResult:
        if not settings.PLAYWRIGHT_ENABLED:
            raise RuntimeError("PLAYWRIGHT_ENABLED=false — 미니PC에서만 켠다")
        if target is None:
            raise ValueError("simulcast 는 spa_page target 이 필요함")
        params = params or {}
        season, year, ym = season_key(params.get("season"), params.get("season_year"))

        await self._check_robots(target.value)
        await self.gate.wait()

        from playwright.async_api import async_playwright  # 무거움 → 필요할 때만 import

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(user_agent=self.ua)
                # 이미지·폰트 차단 → 메모리/트래픽 절약 (어차피 저장 안 함)
                await page.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2}", lambda r: r.abort())
                await page.goto(target.value, wait_until="networkidle", timeout=30_000)

                label = self.sel("season_label", SELECTORS["season_label"]).format(ym=ym)
                if await page.query_selector(label) is None:
                    raise LayoutChanged(f"aniplus simulcast: 분기 체크박스 없음 ({label})")
                await page.click(label)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(1500)   # 필터 후 목록 다시 그리는 시간

                card_sel = self.sel("card", SELECTORS["card"])
                title_sel = self.sel("title", SELECTORS["title"])
                titles = await page.eval_on_selector_all(
                    card_sel, "(els, s) => els.map(e => e.querySelector(s)?.innerText || '')", title_sel,
                )
            finally:
                await browser.close()

        if not titles:
            raise LayoutChanged(f"aniplus simulcast: 카드 0개 (selector={card_sel!r}, {ym})")
        items = build_items(titles, url=target.value, season=season, year=year)
        return CollectResult(items=[self.sanitize(i) for i in items])

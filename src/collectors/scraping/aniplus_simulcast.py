"""애니플러스 TV 동시방영 목록 — SPA 렌더링 (명주). 분기 1회 (+ X 공지로 보정).

- target: target_type='spa_page', value = 동시방영 목록 페이지 URL (TODO: 확인)
- Playwright(Chromium) 로 렌더링 → 작품명·방영 시작일·요일/시간만 추출
- 메모리 큼(브라우저) → 미니PC에서만, settings.PLAYWRIGHT_ENABLED=True 일 때만
- 결과 용도: '어디서 보나'(anime_streaming: platform=aniplus_tv, source=aniplus)
  → event/news 가 아니라 '카탈로그 보강' 흐름 (11_changes 문서 참고)

TODO(07 '기술 확인'):
  [ ] 페이지 URL, 렌더링 후 목록 선택자, 필드 확인
  [ ] robots.txt 확인 (Playwright 도 base_scraper 의 robots 검사를 먼저 통과)
"""
from src.collectors.scraping.base_scraper import BaseScraper
from src.collectors.types import CollectedItem, CollectResult
from src.config.settings import settings
from src.models import ScrapeTarget

CARD_SELECTOR = "[data-simulcast-card]"   # TODO: 실제 선택자
TITLE_SELECTOR = ".title"                 # TODO
SCHEDULE_SELECTOR = ".schedule"           # TODO


class AniplusSimulcastCollector(BaseScraper):
    source_name = "aniplus"
    store_content = False
    default_delay_ms = 3000

    async def collect(self, target: ScrapeTarget | None) -> CollectResult:
        if not settings.PLAYWRIGHT_ENABLED:
            raise RuntimeError("PLAYWRIGHT_ENABLED=false — 미니PC에서만 켠다")
        if target is None:
            raise ValueError("simulcast 는 spa_page target 이 필요함")

        await self._check_robots(target.value)
        await self.gate.wait()

        from playwright.async_api import async_playwright  # 무거움 → 필요할 때만 import

        items: list[CollectedItem] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(user_agent=self.ua)
                # 이미지·폰트 차단 → 메모리/트래픽 절약 (어차피 저장 안 함)
                await page.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2}", lambda r: r.abort())
                await page.goto(target.value, wait_until="networkidle", timeout=30_000)
                for card in await page.query_selector_all(CARD_SELECTOR):
                    title_el = await card.query_selector(TITLE_SELECTOR)
                    sched_el = await card.query_selector(SCHEDULE_SELECTOR)
                    title = (await title_el.inner_text()).strip() if title_el else None
                    if not title:
                        continue
                    items.append(CollectedItem(
                        external_id=f"simulcast:{title}"[:100],
                        url=target.value,
                        title=title[:300],
                        raw_data={"schedule_text": (await sched_el.inner_text()).strip() if sched_el else None,
                                  "platform": "aniplus_tv"},
                    ))
            finally:
                await browser.close()
        return CollectResult(items=[self.sanitize(i) for i in items])

"""DB CHECK 값과 1:1 (ERD v1.2). CHECK를 바꾸면 여기도 같이 바꾼다.

StrEnum → 값이 그냥 문자열이라 DB/JSON 에 그대로 들어감.
"""
from enum import StrEnum


class SourceType(StrEnum):
    API = "api"
    FEED = "feed"
    SCRAPING = "scraping"
    MANUAL = "manual"


class TargetType(StrEnum):
    X_ACCOUNT = "x_account"
    RSS_FEED = "rss_feed"
    SITEMAP = "sitemap"      # 애니플러스 뉴스
    BOARD = "board"          # 애니메이트 게시판
    SPA_PAGE = "spa_page"    # 애니플러스 동시방영 (Playwright)
    KEYWORD = "keyword"      # X 팝업 키워드, 라프텔 작품명


class TargetStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    BROKEN = "broken"


class ScheduleType(StrEnum):
    INTERVAL = "interval"
    CRON = "cron"


class ScrapeJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_finished(self) -> bool:
        return self in (self.COMPLETED, self.FAILED, self.CANCELLED)


class ProcessJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessedCategory(StrEnum):
    """'news' + main.event.type 과 같은 값 (v1.2에서 통일)."""
    NEWS = "news"
    CONCERT = "concert"
    BROADCAST = "broadcast"
    STREAMING = "streaming"
    POPUP = "popup"
    COLLABO_CAFE = "collabo_cafe"
    FAIR = "fair"
    EXHIBITION = "exhibition"
    RELEASE = "release"
    ETC = "etc"

    @property
    def is_event(self) -> bool:
        return self is not ProcessedCategory.NEWS


class ProcessedStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ErrorJobType(StrEnum):
    SCRAPE = "scrape"
    PROCESS = "process"


class ErrorStatus(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class MainSource(StrEnum):
    """main.event.source / news_feed.source 에 들어가는 값 (scrape_source.name 과 같은 이름)."""
    KOPIS = "kopis"
    ANISSIA = "anissia"
    ANIMATE = "animate"
    ANIPLUS = "aniplus"
    X = "x"
    UMJ = "umj"
    MANUAL = "manual"


# news_feed.source 허용값 (ck_news_source)
NEWS_SOURCES = {MainSource.ANIPLUS, MainSource.X, MainSource.UMJ, MainSource.MANUAL}

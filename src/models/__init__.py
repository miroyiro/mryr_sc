"""모델 = 테이블 설계도. 테이블 1개 = 파일 1개 (03 규칙)."""
from src.models.api_cache import ApiCache
from src.models.base import Base
from src.models.process_job import ProcessJob
from src.models.processed_item import ProcessedItem
from src.models.raw_item import RawItem
from src.models.scrape_error import ScrapeError
from src.models.scrape_job import ScrapeJob
from src.models.scrape_schedule import ScrapeSchedule
from src.models.scrape_source import ScrapeSource
from src.models.scrape_target import ScrapeTarget

__all__ = [
    "Base", "ScrapeSource", "ScrapeTarget", "ScrapeSchedule", "ScrapeJob",
    "RawItem", "ProcessJob", "ProcessedItem", "ScrapeError", "ApiCache",
]

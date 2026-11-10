from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from src.models.enums import ScheduleType
from src.schemas.common import ORMModel


class ScheduleOut(ORMModel):
    id: int
    source_id: int
    target_id: int | None
    schedule_type: ScheduleType
    interval_minutes: int | None
    cron_expression: str | None
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None


class ScheduleCreate(BaseModel):
    source_id: int
    target_id: int | None = None
    schedule_type: ScheduleType = ScheduleType.INTERVAL
    interval_minutes: int | None = Field(None, ge=1)
    cron_expression: str | None = Field(None, max_length=50)
    enabled: bool = True

    @model_validator(mode="after")
    def _shape(self):
        # DB의 ck_schedule_shape 와 같은 규칙을 앞단에서 400으로 (DB는 마지막 방어선)
        if self.schedule_type == ScheduleType.INTERVAL and self.interval_minutes is None:
            raise ValueError("interval 스케줄은 interval_minutes 필수")
        if self.schedule_type == ScheduleType.CRON and not self.cron_expression:
            raise ValueError("cron 스케줄은 cron_expression 필수")
        return self


class ScheduleUpdate(BaseModel):
    interval_minutes: int | None = Field(None, ge=1)
    cron_expression: str | None = Field(None, max_length=50)
    enabled: bool | None = None

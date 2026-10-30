"""Resolve bounded relative dates using local wall time before converting to UTC."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import MAX_CORRECTION_DAYS, TIME_OF_DAY_HOURS


@dataclass(frozen=True)
class EventTime:
    ts: datetime
    local_date: date


def map_event_time(
    today_local: date,
    tz: str,
    *,
    relative_day: int = 0,
    time_of_day: str = "unspecified",
) -> EventTime:
    if (
        not isinstance(relative_day, int)
        or isinstance(relative_day, bool)
        or not -MAX_CORRECTION_DAYS <= relative_day <= 0
    ):
        raise ValueError("relative_day must be between -6 and 0")
    if time_of_day not in TIME_OF_DAY_HOURS:
        raise ValueError("Unknown time_of_day")
    local_date = today_local + timedelta(days=relative_day)
    wall_time = datetime.combine(local_date, time(TIME_OF_DAY_HOURS[time_of_day]), ZoneInfo(tz))
    return EventTime(wall_time.astimezone(UTC), local_date)

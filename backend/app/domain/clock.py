"""One source of local dates; callers can supply an aware instant for replay."""

from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class ClockUser(Protocol):
    @property
    def tz(self) -> str: ...

    @property
    def is_demo(self) -> bool: ...

    @property
    def clock_offset_days(self) -> int: ...


def today(user: ClockUser, *, now: datetime | None = None) -> date:
    instant = now if now is not None else datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if user.clock_offset_days and not user.is_demo:
        raise ValueError("A clock offset is allowed only for demo users")
    return instant.astimezone(ZoneInfo(user.tz)).date() + timedelta(days=user.clock_offset_days)

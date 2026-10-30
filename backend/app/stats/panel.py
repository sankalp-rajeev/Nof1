"""Build daily arrays from plain snapshots, preserving calendar gaps as NaNs."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
from numpy.typing import NDArray

from app.stats.config import SHORT_SLEEP_HOURS

FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class PanelEvent:
    local_date: date
    name: str
    kind: str
    status: str
    created_at: datetime
    value: float | None = None
    event_id: str = ""


@dataclass(frozen=True)
class PanelRating:
    local_date: date
    outcome_name: str
    value: float
    updated_at: datetime


@dataclass(frozen=True)
class ChecklistDay:
    local_date: date
    checklist_answered: bool


@dataclass(frozen=True)
class DailyPanel:
    dates: tuple[date, ...]
    outcomes: dict[str, FloatArray]
    exposures: dict[str, FloatArray]
    sleep_hours: FloatArray | None = None

    def __post_init__(self) -> None:
        if any(
            b - a != timedelta(days=1) for a, b in zip(self.dates, self.dates[1:], strict=False)
        ):
            raise ValueError("Panel dates must be a consecutive daily calendar")
        for series in [
            *self.outcomes.values(),
            *self.exposures.values(),
            *([self.sleep_hours] if self.sleep_hours is not None else []),
        ]:
            if series.ndim != 1 or len(series) != len(self.dates) or np.isinf(series).any():
                raise ValueError("Panel arrays must match the calendar and contain no infinities")
        for series in self.exposures.values():
            if not np.all(np.isnan(series) | (series == 0) | (series == 1)):
                raise ValueError("Exposure values must be binary or NaN")
        for series in self.outcomes.values():
            if np.any(np.isfinite(series) & ((series < 0) | (series > 10))):
                raise ValueError("Outcome values must be in 0..10 or NaN")


def build_panel(
    *,
    events: Sequence[PanelEvent],
    ratings: Sequence[PanelRating],
    checkins: Sequence[ChecklistDay],
    tracked_outcomes: Sequence[str],
    tracked_exposures: Sequence[str],
    track_sleep: bool,
) -> DailyPanel:
    if len(set(tracked_outcomes)) != len(tracked_outcomes) or len(set(tracked_exposures)) != len(
        tracked_exposures
    ):
        raise ValueError("Tracked names must be unique")
    if "short_sleep" in tracked_exposures:
        raise ValueError("short_sleep is derived, not a tracked exposure")
    activity = {rating.local_date for rating in ratings}
    activity.update(day.local_date for day in checkins if day.checklist_answered)
    activity.update(event.local_date for event in events if event.kind == "sleep")
    dates = (
        tuple(
            min(activity) + timedelta(days=i)
            for i in range((max(activity) - min(activity)).days + 1)
        )
        if activity
        else ()
    )
    index = {day: i for i, day in enumerate(dates)}
    outcomes = {name: np.full(len(dates), np.nan) for name in tracked_outcomes}
    exposures = {name: np.full(len(dates), np.nan) for name in tracked_exposures}
    sleep = np.full(len(dates), np.nan) if track_sleep else None
    answered = {day.local_date for day in checkins if day.checklist_answered}
    for rating in sorted(ratings, key=lambda item: item.updated_at):
        if rating.outcome_name in outcomes:
            outcomes[rating.outcome_name][index[rating.local_date]] = rating.value
    for event in sorted(events, key=lambda item: (item.created_at, item.event_id)):
        if event.local_date not in index:
            continue
        i = index[event.local_date]
        if event.name in exposures and event.local_date in answered:
            if event.status not in {"done", "skipped"}:
                raise ValueError("Unknown event status")
            exposures[event.name][i] = float(event.status == "done")
        if sleep is not None and event.kind == "sleep":
            sleep[i] = event.value if event.value is not None else np.nan
    if sleep is not None:
        exposures["short_sleep"] = np.where(
            np.isnan(sleep), np.nan, (sleep < SHORT_SLEEP_HOURS).astype(float)
        )
    return DailyPanel(dates, outcomes, exposures, sleep)

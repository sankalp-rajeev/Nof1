from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from app.stats.panel import ChecklistDay, PanelEvent, PanelRating, build_panel

pytestmark = pytest.mark.p2
DAY = date(2026, 1, 1)
STAMP = datetime(2026, 1, 1, tzinfo=UTC)


def test_panel_preserves_calendar_gaps_and_explicit_missingness() -> None:
    events = [
        PanelEvent(DAY, "coffee", "meal", "done", STAMP),
        PanelEvent(DAY + timedelta(days=2), "coffee", "meal", "skipped", STAMP),
        PanelEvent(DAY + timedelta(days=4), "coffee", "meal", "done", STAMP),
        PanelEvent(DAY + timedelta(days=7), "untracked symptom", "symptom", "done", STAMP),
    ]
    panel = build_panel(
        events=events,
        ratings=[
            PanelRating(DAY, "fog", 4, STAMP),
            PanelRating(DAY + timedelta(days=4), "fog", 6, STAMP),
        ],
        checkins=[
            ChecklistDay(DAY + timedelta(days=2), True),
            ChecklistDay(DAY + timedelta(days=4), False),
        ],
        tracked_outcomes=["fog"],
        tracked_exposures=["coffee"],
        track_sleep=False,
    )
    assert panel.dates == tuple(DAY + timedelta(days=i) for i in range(5))
    np.testing.assert_equal(panel.outcomes["fog"], [4, np.nan, np.nan, np.nan, 6])
    np.testing.assert_equal(panel.exposures["coffee"], [np.nan, np.nan, 0, np.nan, np.nan])
    assert set(panel.outcomes) == {"fog"}
    assert panel.sleep_hours is None


def test_panel_latest_corrections_and_sleep_threshold() -> None:
    events = [
        PanelEvent(DAY, "magnesium", "med", "done", STAMP, event_id="a"),
        PanelEvent(DAY, "magnesium", "med", "skipped", STAMP + timedelta(seconds=1)),
        PanelEvent(DAY, "sleep", "sleep", "done", STAMP, value=5.5),
        PanelEvent(DAY + timedelta(days=1), "sleep", "sleep", "done", STAMP, value=6),
        PanelEvent(DAY + timedelta(days=2), "sleep", "sleep", "done", STAMP, value=8),
    ]
    panel = build_panel(
        events=list(reversed(events)),
        ratings=[
            PanelRating(DAY, "fog", 2, STAMP),
            PanelRating(DAY, "fog", 5, STAMP + timedelta(seconds=2)),
        ],
        checkins=[ChecklistDay(DAY, True)],
        tracked_outcomes=["fog"],
        tracked_exposures=["magnesium"],
        track_sleep=True,
    )
    np.testing.assert_equal(panel.exposures["magnesium"], [0, np.nan, np.nan])
    np.testing.assert_equal(panel.exposures["short_sleep"], [1, 0, 0])
    np.testing.assert_equal(panel.sleep_hours, [5.5, 6, 8])
    assert panel.outcomes["fog"][0] == 5


def test_empty_panel_and_unknown_exposure_are_not_zero_filled() -> None:
    empty = build_panel(
        events=[],
        ratings=[],
        checkins=[],
        tracked_outcomes=["fog"],
        tracked_exposures=["walk"],
        track_sleep=True,
    )
    assert empty.dates == ()
    assert empty.exposures["walk"].size == 0
    panel = build_panel(
        events=[],
        ratings=[PanelRating(DAY, "fog", 3, STAMP)],
        checkins=[ChecklistDay(DAY, True)],
        tracked_outcomes=["fog"],
        tracked_exposures=["walk"],
        track_sleep=True,
    )
    assert np.isnan(panel.exposures["walk"][0])
    assert np.isnan(panel.exposures["short_sleep"][0])

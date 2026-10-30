from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.stats.experiment import (
    DayObservation,
    ExperimentProtocol,
    check_eligibility,
    compute_verdict,
    make_protocol,
    schedule,
)

pytestmark = pytest.mark.p2
DAY = date(2026, 2, 1)


def protocol() -> ExperimentProtocol:
    return ExperimentProtocol("walk", "fog", first_block="on", seed=0, start_date=DAY)


def observed(values: tuple[float, float, float, float]) -> list[DayObservation]:
    return [
        DayObservation(plan.date, plan.phase, plan.block, values[plan.block - 1], True)
        for plan in schedule(protocol())
        if plan.block is not None and not plan.washout
    ]


def test_schedule_invariants_both_seeded_orders_and_determinism() -> None:
    first_orders = set()
    for seed in range(20):
        generated = make_protocol("user", str(seed), exposure="walk", outcome="fog", start_date=DAY)
        assert generated == make_protocol(
            "user", str(seed), exposure="walk", outcome="fog", start_date=DAY
        )
        first_orders.add(generated.first_block)
        days = schedule(generated)
        assert len(days) == 14
        assert [plan.date for plan in days] == [DAY + timedelta(days=i) for i in range(14)]
        assert [plan.phase for plan in days[:2]] == ["baseline", "baseline"]
        assert sum(plan.analysis for plan in days) == 8
        for block in range(4):
            chunk = days[2 + block * 3 : 5 + block * 3]
            expected = (
                generated.first_block
                if block % 2 == 0
                else ("off" if generated.first_block == "on" else "on")
            )
            assert {plan.phase for plan in chunk} == {expected}
            assert [plan.washout for plan in chunk] == [True, False, False]
        assert sum(plan.analysis and plan.phase == "on" for plan in days) == 4
        assert sum(plan.analysis and plan.phase == "off" for plan in days) == 4
    assert first_orders == {"on", "off"}


def test_schedule_requires_start_date() -> None:
    with pytest.raises(ValueError, match="start_date"):
        schedule(replace(protocol(), start_date=None))


@pytest.mark.parametrize("category", ["supplement", "food", "habit"])
def test_eligible_exposures(category: str) -> None:
    result = check_eligibility(
        "walk",
        category=category,
        tracked=True,
        done_dates=[DAY + timedelta(days=i) for i in range(5)],
    )
    assert result.eligible and result.reason is None


@pytest.mark.parametrize("category", ["rx_med", "otc_med", "unknown"])
def test_ineligible_categories(category: str) -> None:
    assert not check_eligibility(
        "anything",
        category=category,
        tracked=True,
        done_dates=[DAY + timedelta(days=i) for i in range(5)],
    ).eligible


def test_eligibility_requires_distinct_logged_days_and_refuses_short_sleep() -> None:
    assert not check_eligibility(
        "short_sleep",
        category="habit",
        tracked=True,
        done_dates=[DAY + timedelta(days=i) for i in range(5)],
    ).eligible
    assert not check_eligibility(
        "walk",
        category="habit",
        tracked=False,
        done_dates=[DAY + timedelta(days=i) for i in range(5)],
    ).eligible
    assert not check_eligibility(
        "walk", category="habit", tracked=True, done_dates=[DAY] * 5
    ).eligible


@pytest.mark.parametrize(
    "values,direction,label,reason",
    [
        ((2, 6, 2, 6), "lower", "helped", None),
        ((6, 2, 6, 2), "lower", "worsened", None),
        ((4, 4, 4, 4), "lower", "no_detectable_effect", None),
        ((2, 8, 8, 4), "lower", "inconclusive", "wide_or_inconsistent"),
        ((6, 2, 6, 2), "higher", "helped", None),
        ((2, 6, 2, 6), "higher", "worsened", None),
        ((3, 4, 3, 4), "lower", "helped", None),
    ],
)
def test_verdict_table(
    values: tuple[float, float, float, float], direction: str, label: str, reason: str | None
) -> None:
    data = observed(values)
    verdict = compute_verdict(data, direction_better=direction, seed=1)
    assert verdict["label"] == label and verdict["reason"] == reason
    assert verdict["n_on"] == verdict["n_off"] == 4
    assert verdict["completeness"] == 1
    assert len(verdict["days_used"]) == 8 and verdict["limitation_note_id"]
    assert verdict == compute_verdict(data, direction_better=direction, seed=1)


def test_insufficient_data_precedes_block_missing() -> None:
    days = observed((2, 6, 2, 6))
    days = [replace(day, y=None) if i < 3 else day for i, day in enumerate(days)]
    verdict = compute_verdict(days, direction_better="lower", seed=2)
    assert verdict["label"] == "inconclusive" and verdict["reason"] == "insufficient_data"
    assert verdict["completeness"] == 5 / 8
    assert verdict["benefit"] is None and verdict["ci_low"] is None


def test_six_usable_days_with_one_empty_block() -> None:
    days = [replace(day, y=None) if day.block == 4 else day for day in observed((2, 6, 2, 6))]
    verdict = compute_verdict(days, direction_better="lower", seed=2)
    assert verdict["completeness"] == 6 / 8
    assert verdict["label"] == "inconclusive" and verdict["reason"] == "block_missing"


def test_null_and_false_adherence_are_not_usable_and_snapshot_is_frozen() -> None:
    days = observed((2, 6, 2, 6))
    days[0] = replace(days[0], adherence=None)
    days[2] = replace(days[2], adherence=False)
    verdict = compute_verdict(days, direction_better="lower", seed=3)
    assert verdict["label"] == "helped" and verdict["completeness"] == 6 / 8
    assert verdict["n_on"] == verdict["n_off"] == 3
    days[1] = replace(days[1], y=10)
    assert all(day["y"] != 10 for day in verdict["days_used"])


def test_washout_and_baseline_do_not_enter_verdict() -> None:
    days = observed((2, 6, 2, 6))
    extra = [
        DayObservation(plan.date, plan.phase, plan.block, 10, True, washout=plan.washout)
        for plan in schedule(protocol())
        if not plan.analysis
    ]
    assert compute_verdict(days, direction_better="lower", seed=4) == compute_verdict(
        days + extra, direction_better="lower", seed=4
    )


def test_duplicate_analysis_dates_are_rejected() -> None:
    days = observed((2, 6, 2, 6))
    with pytest.raises(ValueError, match="duplicate"):
        compute_verdict(days + [days[0]], direction_better="lower", seed=0)


def test_generated_protocol_seeds_fit_storage_and_invalid_seeds_are_rejected() -> None:
    for index in range(20):
        generated = make_protocol("seed-user", str(index), exposure="walk", outcome="fog")
        assert 0 <= generated.seed <= (1 << 31) - 1
    with pytest.raises(ValueError, match="seed"):
        replace(protocol(), seed=-1)
    with pytest.raises(ValueError, match="seed"):
        replace(protocol(), seed=1 << 31)

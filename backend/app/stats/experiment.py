"""Pure fixed-protocol scheduling, eligibility checks, and per-protocol verdicts."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, TypedDict

import numpy as np

from app.stats.config import (
    ANALYSIS_DAYS,
    BASELINE_DAYS,
    BLOCK_DAYS,
    BOOTSTRAP_N,
    CI_LEVEL,
    LIMITATION_NOTE_ID,
    MAX_PROTOCOL_SEED,
    MCID,
    MIN_COMPLETENESS,
    MIN_GROUP,
    MIN_USABLE_PER_BLOCK,
    N_BLOCKS,
    WASHOUT_DAYS,
)
from app.stats.randomness import derive_seed

Phase = Literal["baseline", "on", "off"]


@dataclass(frozen=True)
class ExperimentProtocol:
    exposure: str
    outcome: str
    first_block: Literal["on", "off"]
    seed: int
    baseline_days: int = BASELINE_DAYS
    block_days: int = BLOCK_DAYS
    n_blocks: int = N_BLOCKS
    washout_days: int = WASHOUT_DAYS
    start_date: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int) or not 0 <= self.seed <= MAX_PROTOCOL_SEED:
            raise ValueError("Protocol seed must fit a nonnegative PostgreSQL integer")
        if self.first_block not in {"on", "off"} or not self.exposure or not self.outcome:
            raise ValueError("A named exposure/outcome and ON/OFF first block are required")
        if (self.baseline_days, self.block_days, self.n_blocks, self.washout_days) != (
            BASELINE_DAYS,
            BLOCK_DAYS,
            N_BLOCKS,
            WASHOUT_DAYS,
        ):
            raise ValueError("Only the fixed fourteen-day protocol is supported")


@dataclass(frozen=True)
class DayPlan:
    date: date
    phase: Phase
    washout: bool
    block: int | None

    @property
    def analysis(self) -> bool:
        return self.phase != "baseline" and not self.washout


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str | None


@dataclass(frozen=True)
class DayObservation:
    date: date
    phase: Phase
    block: int | None
    y: float | None
    adherence: bool | None
    washout: bool = False


class UsedDay(TypedDict):
    date: str
    phase: Phase
    block: int
    y: float


class Verdict(TypedDict):
    label: str
    reason: str | None
    benefit: float | None
    ci_low: float | None
    ci_high: float | None
    n_on: int
    n_off: int
    completeness: float
    limitation_note_id: str
    days_used: list[UsedDay]


def make_protocol(
    user_id: str, experiment_id: str, *, exposure: str, outcome: str, start_date: date | None = None
) -> ExperimentProtocol:
    seed = derive_seed(user_id, experiment_id) & MAX_PROTOCOL_SEED
    rng = np.random.default_rng(seed)
    first: Literal["on", "off"] = "on" if int(rng.integers(2)) else "off"
    return ExperimentProtocol(exposure, outcome, first, seed, start_date=start_date)


def schedule(protocol: ExperimentProtocol) -> list[DayPlan]:
    if protocol.start_date is None:
        raise ValueError("schedule requires start_date")
    days = [
        DayPlan(protocol.start_date + timedelta(days=i), "baseline", False, None)
        for i in range(protocol.baseline_days)
    ]
    opposite: Literal["on", "off"] = "off" if protocol.first_block == "on" else "on"
    for block in range(protocol.n_blocks):
        phase = protocol.first_block if block % 2 == 0 else opposite
        for offset in range(protocol.block_days):
            day = protocol.start_date + timedelta(
                days=protocol.baseline_days + block * protocol.block_days + offset
            )
            days.append(DayPlan(day, phase, offset < protocol.washout_days, block + 1))
    return days


def check_eligibility(
    exposure: str, *, category: str, tracked: bool, done_dates: Sequence[date]
) -> Eligibility:
    if exposure == "short_sleep":
        return Eligibility(False, "derived_exposure")
    if category not in {"supplement", "food", "habit"}:
        return Eligibility(False, "ineligible_category")
    if not tracked:
        return Eligibility(False, "not_tracked")
    if len(set(done_dates)) < MIN_GROUP:
        return Eligibility(False, "insufficient_exposure")
    return Eligibility(True, None)


def _usable_days(days: Sequence[DayObservation]) -> list[UsedDay]:
    if len({day.date for day in days}) != len(days):
        raise ValueError("duplicate observation date")
    usable: list[UsedDay] = []
    phases: dict[int, Phase] = {}
    counts: dict[int, int] = {}
    for day in sorted(days, key=lambda item: item.date):
        if day.phase not in {"baseline", "on", "off"}:
            raise ValueError("Unknown scheduled phase")
        if day.y is not None and (not math.isfinite(day.y) or not 0 <= day.y <= 10):
            raise ValueError("Ratings must be finite and in 0..10")
        if day.phase == "baseline" or day.washout:
            continue
        if day.block is None or not 1 <= day.block <= N_BLOCKS:
            raise ValueError("Analysis day requires block 1..4")
        counts[day.block] = counts.get(day.block, 0) + 1
        if counts[day.block] > BLOCK_DAYS - WASHOUT_DAYS:
            raise ValueError("Too many analysis days in a block")
        if day.block in phases and phases[day.block] != day.phase:
            raise ValueError("A block must use one scheduled phase")
        phases[day.block] = day.phase
        if day.adherence is True and day.y is not None:
            usable.append(
                UsedDay(date=day.date.isoformat(), phase=day.phase, block=day.block, y=float(day.y))
            )
    first_on = {((block % 2 == 1) == (phase == "on")) for block, phase in phases.items()}
    if len(first_on) > 1:
        raise ValueError("Experiment blocks must alternate ON and OFF")
    return usable


def _benefit(on: float, off: float, direction: str) -> float:
    return off - on if direction == "lower" else on - off


def compute_verdict(days: Sequence[DayObservation], *, direction_better: str, seed: int) -> Verdict:
    if direction_better not in {"lower", "higher"}:
        raise ValueError("direction_better must be lower or higher")
    usable = _usable_days(days)
    on = np.array([day["y"] for day in usable if day["phase"] == "on"], dtype=float)
    off = np.array([day["y"] for day in usable if day["phase"] == "off"], dtype=float)
    result = Verdict(
        label="inconclusive",
        reason=None,
        benefit=None,
        ci_low=None,
        ci_high=None,
        n_on=len(on),
        n_off=len(off),
        completeness=len(usable) / ANALYSIS_DAYS,
        limitation_note_id=LIMITATION_NOTE_ID,
        days_used=usable,
    )
    if result["completeness"] < MIN_COMPLETENESS:
        result["reason"] = "insufficient_data"
        return result
    if any(
        sum(day["block"] == block for day in usable) < MIN_USABLE_PER_BLOCK
        for block in range(1, N_BLOCKS + 1)
    ):
        result["reason"] = "block_missing"
        return result
    benefit = _benefit(float(on.mean()), float(off.mean()), direction_better)
    rng = np.random.default_rng(seed)
    on_samples = rng.choice(on, size=(BOOTSTRAP_N, len(on)), replace=True).mean(axis=1)
    off_samples = rng.choice(off, size=(BOOTSTRAP_N, len(off)), replace=True).mean(axis=1)
    samples = off_samples - on_samples if direction_better == "lower" else on_samples - off_samples
    tail = (1 - CI_LEVEL) / 2
    low, high = (float(value) for value in np.quantile(samples, [tail, 1 - tail], method="linear"))
    pair_benefits: list[float] = []
    for first in (1, 3):
        pair_on = [
            day["y"]
            for day in usable
            if day["block"] in (first, first + 1) and day["phase"] == "on"
        ]
        pair_off = [
            day["y"]
            for day in usable
            if day["block"] in (first, first + 1) and day["phase"] == "off"
        ]
        pair_benefits.append(
            _benefit(float(np.mean(pair_on)), float(np.mean(pair_off)), direction_better)
        )
    consistent = all(value * benefit > 0 for value in pair_benefits)
    result["benefit"] = benefit
    result["ci_low"] = low
    result["ci_high"] = high
    if low > 0 and benefit >= MCID and consistent:
        result["label"] = "helped"
    elif high < 0 and benefit <= -MCID and consistent:
        result["label"] = "worsened"
    elif low > -MCID and high < MCID:
        result["label"] = "no_detectable_effect"
    else:
        result["reason"] = "wide_or_inconsistent"
    return result

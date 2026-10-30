"""Specified stochastic world, separate from observable daily panel snapshots."""

import copy
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, cast

import numpy as np

from app.stats.config import SHORT_SLEEP_HOURS
from app.stats.experiment import DayObservation, ExperimentProtocol, schedule
from app.stats.panel import DailyPanel
from app.stats.randomness import derive_seed
from sim.config import (
    DEV_SEED_MAX,
    DEV_SEED_MIN,
    EFFECT_SIZES,
    EXPOSURES,
    OUTCOME,
    PATIENT_TYPES,
    PATIENT_WEIGHTS,
    START_DATE,
)

PatientType = Literal["null", "single_effect", "double_effect", "confounded_null"]


@dataclass(frozen=True)
class PlantedEffect:
    exposure: str
    outcome: str
    lag: int
    beta: float


@dataclass(frozen=True)
class GroundTruth:
    seed: int
    patient_type: PatientType
    effects: tuple[PlantedEffect, ...]
    confounded_exposure: str | None
    gamma: float
    probabilities: tuple[float, ...]
    stickiness: tuple[float, ...]
    phi: float
    sigma: float
    base: float
    p_miss: float
    checklist_error: float


@dataclass(frozen=True)
class SimDay:
    date: date
    exposures: tuple[int, ...]
    reported_exposures: tuple[int, ...]
    sleep_hours: float
    y: float
    observed: bool


@dataclass(frozen=True)
class WorldState:
    z: float | None
    previous_exposures: tuple[int, ...] | None
    exposure_history: tuple[tuple[int, ...], ...]
    observed: bool
    rng_state: dict[str, object]


@dataclass(frozen=True)
class World:
    truth: GroundTruth
    days: tuple[SimDay, ...]
    state: WorldState


@dataclass(frozen=True)
class ExperimentSimulation:
    days: tuple[SimDay, ...]
    observations: tuple[DayObservation, ...]
    state: WorldState


def _truth(
    seed: int,
    patient_type: PatientType | None,
    forced_effect: PlantedEffect | None,
    checklist_error: float,
) -> GroundTruth:
    rng = np.random.default_rng(seed)
    sampled = cast(PatientType, str(rng.choice(PATIENT_TYPES, p=PATIENT_WEIGHTS)))
    kind = patient_type if patient_type is not None else sampled
    if kind not in PATIENT_TYPES:
        raise ValueError("Unknown patient type")
    probabilities = tuple(float(value) for value in rng.uniform(0.3, 0.8, 6))
    stickiness = tuple(float(value) for value in rng.uniform(0, 0.5, 6))
    phi, sigma, base, p_miss = (
        float(rng.uniform(0.2, 0.6)),
        float(rng.uniform(0.8, 1.5)),
        float(rng.uniform(2, 5)),
        float(rng.uniform(0.1, 0.4)),
    )
    gamma = float(rng.uniform(1, 1.5)) if kind == "confounded_null" else float(rng.uniform(0, 0.6))
    confounded = EXPOSURES[int(rng.integers(6))] if kind == "confounded_null" else None
    count = 1 if kind == "single_effect" else 2 if kind == "double_effect" else 0
    indices = rng.choice(6, size=count, replace=False)
    effects = tuple(
        PlantedEffect(
            EXPOSURES[int(index)],
            OUTCOME,
            int(rng.integers(3)),
            float(rng.choice(EFFECT_SIZES)) * int(rng.choice([-1, 1])),
        )
        for index in indices
    )
    if forced_effect is not None:
        if (
            kind != "single_effect"
            or forced_effect.exposure not in EXPOSURES
            or forced_effect.outcome != OUTCOME
            or forced_effect.lag not in (0, 1, 2)
        ):
            raise ValueError("Forced effect must describe the single-effect evaluation world")
        effects = (forced_effect,)
    return GroundTruth(
        seed,
        kind,
        effects,
        confounded,
        gamma,
        probabilities,
        stickiness,
        phi,
        sigma,
        base,
        p_miss,
        checklist_error,
    )


def _step(
    truth: GroundTruth,
    rng: np.random.Generator,
    state: WorldState,
    day: date,
    *,
    force: tuple[int, int] | None = None,
) -> tuple[SimDay, WorldState]:
    observed = (
        True
        if state.z is None
        else (
            bool(rng.random() >= 0.5 * truth.p_miss / (1 - truth.p_miss))
            if state.observed
            else bool(rng.random() < 0.5)
        )
    )
    sleep = float(np.clip(rng.normal(7, 1), 4, 10))
    values: list[int] = []
    for index, (p, stickiness) in enumerate(
        zip(truth.probabilities, truth.stickiness, strict=True)
    ):
        if EXPOSURES[index] == truth.confounded_exposure:
            chance = float(np.clip(p + 0.25 * (7 - sleep), 0.05, 0.95))
        elif state.previous_exposures is None:
            chance = p
        else:
            chance = (
                p + stickiness * (1 - p)
                if state.previous_exposures[index]
                else p * (1 - stickiness)
            )
        values.append(int(rng.random() < chance))
    if force is not None:
        values[force[0]] = force[1]
    exposures = tuple(values)
    z = (
        float(rng.normal(0, truth.sigma / np.sqrt(1 - truth.phi**2)))
        if state.z is None
        else truth.phi * state.z + float(rng.normal(0, truth.sigma))
    )
    effect = 0.0
    for planted in truth.effects:
        source = exposures if planted.lag == 0 else state.exposure_history[-planted.lag]
        effect += planted.beta * source[EXPOSURES.index(planted.exposure)]
    y = float(
        np.clip(
            np.rint(truth.base + z + effect + truth.gamma * (7 - sleep) + rng.normal(0, 0.5)), 0, 10
        )
    )
    flips = rng.random(6) < truth.checklist_error
    reported = tuple(1 - value if flips[index] else value for index, value in enumerate(exposures))
    result = SimDay(day, exposures, reported, sleep, y, observed)
    next_state = WorldState(
        z,
        exposures,
        (*state.exposure_history[-1:], exposures),
        observed,
        copy.deepcopy(dict(rng.bit_generator.state)),
    )
    return result, next_state


def generate_world(
    seed: int,
    *,
    days: int = 60,
    patient_type: PatientType | None = None,
    forced_effect: PlantedEffect | None = None,
    checklist_error: float = 0,
) -> World:
    if not DEV_SEED_MIN <= seed <= DEV_SEED_MAX:
        raise ValueError("Only dev seeds 0..9999 are permitted outside eval-final")
    if days < 1 or not 0 <= checklist_error <= 1:
        raise ValueError("Positive duration and checklist_error in [0,1] required")
    truth = _truth(seed, patient_type, forced_effect, checklist_error)
    rng = np.random.default_rng(derive_seed(str(seed), "world-history"))
    prehistory = tuple(tuple(int(rng.random() < p) for p in truth.probabilities) for _ in range(2))
    state = WorldState(None, None, prehistory, True, copy.deepcopy(dict(rng.bit_generator.state)))
    history: list[SimDay] = []
    for index in range(days):
        result, state = _step(truth, rng, state, START_DATE + timedelta(days=index))
        history.append(result)
    return World(truth, tuple(history), state)


def world_to_panel(world: World) -> DailyPanel:
    observed = np.array([day.observed for day in world.days])
    last = int(np.flatnonzero(observed)[-1]) + 1
    observed = observed[:last]
    days = world.days[:last]
    exposures = {
        name: np.where(
            observed, np.array([day.reported_exposures[index] for day in days], dtype=float), np.nan
        )
        for index, name in enumerate(EXPOSURES)
    }
    sleep = np.where(observed, np.array([day.sleep_hours for day in days]), np.nan)
    exposures["short_sleep"] = np.where(observed, (sleep < SHORT_SLEEP_HOURS).astype(float), np.nan)
    outcomes = {OUTCOME: np.where(observed, np.array([day.y for day in days]), np.nan)}
    return DailyPanel(tuple(day.date for day in days), outcomes, exposures, sleep)


def simulate_experiment(
    world: World, protocol: ExperimentProtocol, adherence_p: float
) -> ExperimentSimulation:
    if (
        not 0 <= adherence_p <= 1
        or protocol.exposure not in EXPOSURES
        or protocol.outcome != OUTCOME
    ):
        raise ValueError("Invalid adherence probability or experiment target")
    if protocol.start_date != world.days[-1].date + timedelta(days=1):
        raise ValueError("Experiment must continue on the day after the history")
    rng = np.random.default_rng(0)
    rng.bit_generator.state = copy.deepcopy(world.state.rng_state)
    state = world.state
    days: list[SimDay] = []
    observations: list[DayObservation] = []
    index = EXPOSURES.index(protocol.exposure)
    for plan in schedule(protocol):
        adherence = bool(rng.random() < adherence_p) if plan.phase != "baseline" else None
        force = (index, int(plan.phase == "on")) if adherence else None
        day, state = _step(world.truth, rng, state, plan.date, force=force)
        days.append(day)
        observations.append(
            DayObservation(
                day.date,
                plan.phase,
                plan.block,
                day.y if day.observed else None,
                adherence if day.observed else None,
                plan.washout,
            )
        )
    return ExperimentSimulation(tuple(days), tuple(observations), state)

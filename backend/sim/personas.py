"""Seeded cards, mention plans and follow-up truth; no provider or planted-effect input."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import Field

from app.domain.normalize import normalize
from app.domain.schemas import (
    ConfirmExperiment,
    ConfirmTrack,
    DomainModel,
    ExperimentAdherence,
    ExposureChecklist,
    Pending,
    RateOutcome,
    SleepHours,
)
from app.stats.randomness import derive_seed
from sim.config import (
    COMPLIANCE_P,
    DROPOUT_P,
    EXPOSURES,
    OUTCOME,
    SEVERITY_NOISE_P,
)
from sim.extraction import Label
from sim.final_scope import permitted_seed
from sim.world import SimDay


class Persona(DomainModel):
    verbosity: Literal["terse", "normal", "rambly"]
    typo_rate: float = Field(ge=0, le=0.08)
    tone: Literal["flat", "upbeat", "anxious", "dry"]
    emoji: bool
    abbreviations: bool
    omission_rate: float = Field(ge=0, le=0.3)
    fatigue_sensitivity: bool


def persona_card(seed: int) -> Persona:
    if not permitted_seed(seed):
        raise ValueError("Persona seed must be a development seed")
    rng = np.random.default_rng(derive_seed(str(seed), "persona"))
    return Persona(
        verbosity=("terse", "normal", "rambly")[int(rng.integers(3))],
        typo_rate=float(rng.uniform(0, 0.08)),
        tone=("flat", "upbeat", "anxious", "dry")[int(rng.integers(4))],
        emoji=bool(rng.integers(2)),
        abbreviations=bool(rng.integers(2)),
        omission_rate=float(rng.uniform(0, 0.3)),
        fatigue_sensitivity=bool(rng.integers(2)),
    )


def observed_events(day: SimDay, *, checklist: bool = False) -> tuple[Label, ...]:
    return (
        *(
            Label(
                kind=normalize(name).kind or "life",
                name=name,
                status="done" if value else "skipped",
            )
            for name, value in zip(
                EXPOSURES, day.reported_exposures if checklist else day.exposures, strict=True
            )
        ),
        Label(kind="symptom", name=OUTCOME, severity=int(day.y)),
        Label(kind="sleep", name="sleep", value=round(day.sleep_hours, 1), unit="h"),
    )


def mention_plan(events: tuple[Label, ...], persona: Persona, *, seed: int) -> tuple[Label, ...]:
    rng = np.random.default_rng(derive_seed(str(seed), "mentions"))
    return tuple(event for event in events if rng.random() >= persona.omission_rate)


@dataclass(frozen=True)
class Followup:
    events: tuple[Label, ...] = ()
    fixed: str | None = None


def persona_reply(
    pending: Pending | None,
    events: tuple[Label, ...],
    *,
    seed: int,
    adherence: bool | None = None,
) -> Followup:
    """Answer only the requested observation; absent observations stay unknown.

    Checklist names never undergo omission. Severity noise is seeded and bounded.
    Confirmation/adherence decisions are supplied by code, never invented by a model.
    """
    if isinstance(pending, RateOutcome):
        event = next(
            (
                e
                for e in events
                if e.kind == "symptom"
                and normalize(e.name).canonical == normalize(pending.outcome).canonical
            ),
            None,
        )
        if event is not None and event.severity is not None:
            rng = np.random.default_rng(derive_seed(str(seed), "severity-noise"))
            noise = int(rng.choice([-1, 1])) if rng.random() < SEVERITY_NOISE_P else 0
            return Followup(
                (event.model_copy(update={"severity": min(10, max(0, event.severity + noise))}),)
            )
    elif isinstance(pending, SleepHours):
        event = next((e for e in events if e.kind == "sleep"), None)
        if event is not None:
            return Followup((event,))
    elif isinstance(pending, ExposureChecklist):
        names = {normalize(name).canonical for name in pending.names}
        selected = tuple(e for e in events if normalize(e.name).canonical in names)
        if {normalize(e.name).canonical for e in selected} == names:
            return Followup(selected)
    elif isinstance(pending, ExperimentAdherence):
        return (
            Followup(fixed="yes" if adherence else "no")
            if adherence is not None
            else Followup(fixed="skip")
        )
    elif isinstance(pending, ConfirmExperiment):
        return Followup(fixed="yes")
    elif isinstance(pending, ConfirmTrack):
        return Followup(fixed="no")  # Preserve the cohort's fixed tracking configuration.
    return Followup(fixed="skip")


def participation(seed: int, day_index: int) -> tuple[bool, bool]:
    rng = np.random.default_rng(derive_seed(str(seed), f"participation:{day_index}"))
    return bool(rng.random() < DROPOUT_P), bool(rng.random() < COMPLIANCE_P)

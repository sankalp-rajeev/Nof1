"""Offline cohort orchestration. Only observed panels cross into the scanner."""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from pydantic import JsonValue, TypeAdapter

from app.stats import config as stats_config
from app.stats.experiment import compute_verdict, make_protocol
from app.stats.panel import DailyPanel
from app.stats.patterns import ScanResult, scan_patterns
from app.stats.randomness import derive_seed
from sim.config import ADHERENCE_P, COHORT_A, COHORT_N, COHORT_V, EXPOSURES, OUTCOME, VERDICT_LABELS
from sim.report import Cohort, EvaluationReport, Rate, VerdictCell
from sim.scoring import Claim, PatternScore, score_patterns
from sim.world import (
    GroundTruth,
    PlantedEffect,
    generate_world,
    simulate_experiment,
    world_to_panel,
)


@dataclass(frozen=True)
class PatientEvaluation:
    truth: GroundTruth
    score: PatternScore


def run_scan(panel: DailyPanel, *, identity: str, n_perm: int) -> ScanResult:
    return scan_patterns(panel, user_id=identity, purpose="stats-eval", n_perm=n_perm)


def evaluate_scans(
    seeds: Sequence[int], *, days: int, n_perm: int, progress: Callable[[str], None] | None = None
) -> list[PatientEvaluation]:
    results: list[PatientEvaluation] = []
    for index, seed in enumerate(seeds):
        world = generate_world(seed, days=days)
        output = run_scan(world_to_panel(world), identity=f"sim-{seed}", n_perm=n_perm)
        claims = [
            Claim(p.exposure, p.outcome, p.lag_days, p.effect, p.confounder)
            for p in output.patterns
        ]
        results.append(PatientEvaluation(world.truth, score_patterns(world.truth, claims)))
        if progress and (index + 1) % 100 == 0:
            progress(f"T={days}, n_perm={n_perm}: {index + 1}/{len(seeds)} patients")
    return results


def _power(patients: list[PatientEvaluation]) -> dict[str, Rate]:
    counts: dict[float, list[bool]] = {magnitude: [] for magnitude in (1.0, 1.5, 2.0, 3.0)}
    for patient in patients:
        for effect, hit in zip(patient.truth.effects, patient.score.hits, strict=True):
            if effect.exposure != "short_sleep" and abs(effect.beta) in counts:
                counts[abs(effect.beta)].append(hit)
    return {str(beta): Rate(sum(hits), len(hits)) for beta, hits in counts.items()}


def _cohort(seeds: Sequence[int], days: int) -> Cohort:
    return Cohort(len(seeds), min(seeds) if seeds else None, max(seeds) if seeds else None, days)


def _experiment(seed: int, *, beta: float | None = None) -> tuple[str, float]:
    exposure = EXPOSURES[seed % len(EXPOSURES)]
    forced = PlantedEffect(exposure, OUTCOME, 0, beta) if beta is not None else None
    world = generate_world(
        seed, patient_type="single_effect" if forced else "null", forced_effect=forced
    )
    protocol = make_protocol(
        f"sim-{seed}",
        "evaluation",
        exposure=exposure,
        outcome=OUTCOME,
        start_date=world.days[-1].date + timedelta(days=1),
    )
    result = simulate_experiment(world, protocol, ADHERENCE_P)
    verdict = compute_verdict(
        result.observations, direction_better="lower", seed=derive_seed(str(seed), "verdict")
    )
    return verdict["label"], verdict["completeness"]


def evaluate_suite(
    *,
    n_perm: int,
    include_power: bool = True,
    include_verdicts: bool = True,
    scan_seeds: Sequence[int] = COHORT_A,
    null_seeds: Sequence[int] = COHORT_N,
    progress: Callable[[str], None] | None = None,
) -> EvaluationReport:
    patients = evaluate_scans(scan_seeds, days=60, n_perm=n_perm, progress=progress)
    nulls = [patient for patient in patients if patient.truth.patient_type == "null"]
    confounded = [
        patient for patient in patients if patient.truth.patient_type == "confounded_null"
    ]
    power = {"60": _power(patients)}
    cohorts = {"A": _cohort(scan_seeds, 60), "N": _cohort(null_seeds, 14)}
    if include_power:
        power["30"] = _power(evaluate_scans(scan_seeds, days=30, n_perm=n_perm, progress=progress))
        cohorts["A30"] = _cohort(scan_seeds, 30)
    e1c = {
        name: Rate(
            sum(getattr(patient.score, attribute) for patient in confounded), len(confounded)
        )
        for name, attribute in [
            ("any", "confounded_any"),
            ("flagged", "confounded_flagged"),
            ("unflagged", "confounded_unflagged"),
        ]
    }
    ordered = sorted(patients, key=lambda patient: (patient.truth.gamma, patient.truth.seed))
    groups = np.array_split(np.arange(len(ordered)), 3)
    e1s = {
        name: Rate(sum(ordered[int(index)].score.short_sleep for index in group), len(group))
        for name, group in zip(("low", "middle", "high"), groups, strict=True)
    }
    null_labels = [_experiment(seed)[0] for seed in null_seeds]
    e3 = Rate(sum(label in {"helped", "worsened"} for label in null_labels), len(null_labels))
    e3b: dict[str, VerdictCell] = {}
    completeness: list[float] = []
    if include_verdicts:
        for cell, (magnitude, sign) in enumerate(
            (magnitude, sign)
            for magnitude in (0.0, 1.0, 2.0, 3.0)
            for sign in ("beneficial", "harmful")
        ):
            beta = -magnitude if sign == "beneficial" else magnitude
            values = [
                _experiment(seed, beta=beta)
                for seed in range(COHORT_V.start + cell * 100, COHORT_V.start + (cell + 1) * 100)
            ]
            labels = Counter(label for label, _ in values)
            reference = (
                "no_detectable_effect|inconclusive"
                if magnitude == 0
                else "helped"
                if sign == "beneficial"
                else "worsened"
            )
            correct = sum(labels[label] for label in reference.split("|"))
            e3b[f"{magnitude}:{sign}"] = VerdictCell(
                {label: labels[label] for label in VERDICT_LABELS}, reference, correct, len(values)
            )
            completeness.extend(value for _, value in values)
        cohorts["V"] = _cohort(COHORT_V, 14)
    configuration = {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in vars(stats_config).items()
        if name.isupper() and isinstance(value, (str, int, float, tuple))
    }
    return EvaluationReport(
        n_perm,
        cohorts,
        Rate(sum(patient.score.null_flag for patient in nulls), len(nulls)),
        power["60"]["3.0"],
        e3,
        e1c,
        e1s,
        power,
        e3b,
        tuple(completeness),
        TypeAdapter(dict[str, JsonValue]).validate_python(configuration),
    )

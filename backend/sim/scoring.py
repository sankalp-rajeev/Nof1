"""Pure matching and regression comparisons; no persistence, LLMs, or network."""

from collections.abc import Sequence
from dataclasses import dataclass

from sim.config import REGRESSION_FALSE_POSITIVE_RISE, REGRESSION_RECALL_DROP
from sim.world import GroundTruth


@dataclass(frozen=True)
class Claim:
    exposure: str
    outcome: str
    lag_days: int
    effect: float
    confounder: str | None = None


@dataclass(frozen=True)
class PatternScore:
    hits: tuple[bool, ...]
    false_positives: int
    null_flag: bool
    short_sleep: bool
    confounded_any: bool
    confounded_flagged: bool
    confounded_unflagged: bool


def score_patterns(truth: GroundTruth, patterns: Sequence[Claim]) -> PatternScore:
    hits = [False] * len(truth.effects)
    false_positives = 0
    non_sleep = [claim for claim in patterns if claim.exposure != "short_sleep"]
    for claim in non_sleep:
        match = next(
            (
                index
                for index, planted in enumerate(truth.effects)
                if not hits[index]
                and planted.exposure == claim.exposure
                and planted.outcome == claim.outcome
                and planted.lag == claim.lag_days
                and planted.beta * claim.effect > 0
            ),
            None,
        )
        if match is None:
            false_positives += 1
        else:
            hits[match] = True
    confounded = (
        [claim for claim in non_sleep if claim.exposure == truth.confounded_exposure]
        if truth.patient_type == "confounded_null"
        else []
    )
    return PatternScore(
        tuple(hits),
        false_positives,
        truth.patient_type == "null" and bool(non_sleep),
        any(claim.exposure == "short_sleep" for claim in patterns),
        bool(confounded),
        any(claim.confounder is not None for claim in confounded),
        any(claim.confounder is None for claim in confounded),
    )


def compare_regression(
    current: dict[str, dict[str, float]], baseline: dict[str, dict[str, float]]
) -> list[str]:
    issues: list[str] = []
    if "stats" not in current or "stats" not in baseline:
        return issues
    for metric, allowance, direction in [
        ("E1", REGRESSION_FALSE_POSITIVE_RISE, 1),
        ("E2", REGRESSION_RECALL_DROP, -1),
        ("E3", REGRESSION_FALSE_POSITIVE_RISE, 1),
    ]:
        observed, reference = current["stats"][metric], baseline["stats"][metric]
        if (observed - reference) * direction > allowance + 1e-12:
            issues.append(f"{metric}: {observed:.6f} versus baseline {reference:.6f}")
    return issues

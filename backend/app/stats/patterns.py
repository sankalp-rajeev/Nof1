"""Pure lagged scans with hybrid block-permutation inference and BH correction."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from app.stats.config import (
    BLOCK_LEN,
    CONFOUNDER_R,
    FDR_Q,
    LAGS,
    MAX_PATTERNS_STORED,
    MIN_EFFECT,
    MIN_FULL_BLOCKS,
    MIN_GROUP,
    MIN_PAIRS,
    MODERATE_EFFECT,
    MODERATE_MIN_PAIRS,
    MODERATE_Q,
    N_PERM,
    PERM_BATCH_SIZE,
    PERM_MAX_DRAW_FACTOR,
    PERM_MIN_VALID_SHARE,
    PERM_TIE_TOLERANCE,
)
from app.stats.panel import DailyPanel, FloatArray
from app.stats.randomness import derive_seed

PermMode = Literal["exact", "mc"]
IntArray = NDArray[np.int64]


@dataclass(frozen=True)
class PermutationResult:
    effect: float
    n_pairs: int
    n_exposed: int
    n_unexposed: int
    p_value: float | None
    perm_mode: PermMode
    n_valid: int
    n_draws: int
    stable: bool


@dataclass(frozen=True)
class EvidencePoint:
    outcome_date: date
    exposure_date: date
    x: float
    y: float


@dataclass(frozen=True)
class Pattern:
    pattern_key: str
    exposure: str
    outcome: str
    lag_days: int
    effect: float
    p_raw: float
    p_adj: float
    tier: Literal["weak", "moderate"]
    n_pairs: int
    n_exposed: int
    n_unexposed: int
    perm_mode: PermMode
    n_valid: int
    confounder: str | None
    window_start: date
    window_end: date
    data_points: tuple[EvidencePoint, ...]


@dataclass(frozen=True)
class ScanTest:
    exposure: str
    outcome: str
    lag: int
    result: PermutationResult
    p_adj: float | None = None


@dataclass(frozen=True)
class ScanResult:
    patterns: tuple[Pattern, ...]
    tests: tuple[ScanTest, ...]


def permutation_mode(blocks: int, n_perm: int) -> PermMode:
    if blocks < 0 or n_perm < 1:
        raise ValueError("Nonnegative block count and positive permutation budget required")
    orderings = 1
    for factor in range(2, blocks + 1):
        orderings *= factor
        if orderings > n_perm:
            return "mc"
    return "exact"


def _validate_series(x: FloatArray, y: FloatArray, lag: int, n_perm: int) -> None:
    if lag not in LAGS or n_perm < 1:
        raise ValueError("Unsupported lag or permutation budget")
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise ValueError("Expected equal-length one-dimensional series")
    if not np.all(np.isnan(x) | (x == 0) | (x == 1)) or np.isinf(y).any():
        raise ValueError("Invalid exposure or outcome value")


def _summary(x: FloatArray, y: FloatArray, lag: int) -> tuple[float, int, int, int] | None:
    px, py = (x[:-lag] if lag else x), y[lag:]
    mask = np.isfinite(px) & np.isfinite(py)
    exposed, unexposed = mask & (px == 1), mask & (px == 0)
    pairs, n_on, n_off = int(mask.sum()), int(exposed.sum()), int(unexposed.sum())
    if pairs < MIN_PAIRS or min(n_on, n_off) < MIN_GROUP:
        return None
    return float(py[exposed].mean() - py[unexposed].mean()), pairs, n_on, n_off


def _draw_block_orders(rng: np.random.Generator, blocks: int, count: int) -> IntArray:
    base = np.broadcast_to(np.arange(blocks, dtype=np.int64), (count, blocks))
    return rng.permuted(base, axis=1)


def _batch_counts(
    x: FloatArray, y: FloatArray, lag: int, orders: IntArray, observed: float
) -> tuple[int, int]:
    blocks = len(x) // BLOCK_LEN
    indices = (orders[:, :, None] * BLOCK_LEN + np.arange(BLOCK_LEN)).reshape(len(orders), -1)
    permuted = x[indices]
    tail = x[blocks * BLOCK_LEN :]
    if tail.size:
        permuted = np.concatenate(
            [permuted, np.broadcast_to(tail, (len(orders), len(tail)))], axis=1
        )
    px, py = (permuted[:, :-lag] if lag else permuted), y[lag:]
    mask = np.isfinite(px) & np.isfinite(py)
    on, off = mask & (px == 1), mask & (px == 0)
    n_on, n_off = on.sum(axis=1), off.sum(axis=1)
    valid = (mask.sum(axis=1) >= MIN_PAIRS) & (n_on >= MIN_GROUP) & (n_off >= MIN_GROUP)
    means_on = np.divide(
        np.where(on, py, 0).sum(axis=1), n_on, out=np.zeros(len(orders)), where=n_on > 0
    )
    means_off = np.divide(
        np.where(off, py, 0).sum(axis=1), n_off, out=np.zeros(len(orders)), where=n_off > 0
    )
    magnitude = np.abs(means_on - means_off)
    extreme = (magnitude >= abs(observed)) | np.isclose(
        magnitude, abs(observed), rtol=PERM_TIE_TOLERANCE, atol=PERM_TIE_TOLERANCE
    )
    return int(valid.sum()), int((valid & extreme).sum())


def _permutation_test(
    x: FloatArray, y: FloatArray, *, lag: int, seed: int, n_perm: int, mode: PermMode
) -> PermutationResult | None:
    _validate_series(x, y, lag, n_perm)
    observed = _summary(x, y, lag)
    blocks = len(x) // BLOCK_LEN
    if observed is None or blocks < MIN_FULL_BLOCKS:
        return None
    effect, pairs, n_on, n_off = observed
    n_valid = extreme = draws = 0
    if mode == "exact":
        iterator = itertools.permutations(range(blocks))
        while batch := list(itertools.islice(iterator, PERM_BATCH_SIZE)):
            valid, hits = _batch_counts(x, y, lag, np.array(batch, dtype=np.int64), effect)
            n_valid += valid
            extreme += hits
            draws += len(batch)
        stable = n_valid / draws >= PERM_MIN_VALID_SHARE
        p_value = extreme / n_valid if n_valid else None
    else:
        rng = np.random.default_rng(seed)
        while n_valid < n_perm and draws < PERM_MAX_DRAW_FACTOR * n_perm:
            count = min(PERM_BATCH_SIZE, n_perm - n_valid, PERM_MAX_DRAW_FACTOR * n_perm - draws)
            orders = _draw_block_orders(rng, blocks, count)
            valid, hits = _batch_counts(x, y, lag, orders, effect)
            n_valid += valid
            extreme += hits
            draws += count
        stable = n_valid >= PERM_MIN_VALID_SHARE * n_perm
        p_value = (1 + extreme) / (1 + n_valid)
    return PermutationResult(effect, pairs, n_on, n_off, p_value, mode, n_valid, draws, stable)


def block_permutation_test(
    x: FloatArray, y: FloatArray, *, lag: int, seed: int, n_perm: int = N_PERM
) -> PermutationResult | None:
    """Choose the normative exact/MC mode; return None for insufficient observed data."""
    return _permutation_test(
        x, y, lag=lag, seed=seed, n_perm=n_perm, mode=permutation_mode(len(x) // BLOCK_LEN, n_perm)
    )


def monte_carlo_test(
    x: FloatArray, y: FloatArray, *, lag: int, seed: int, n_perm: int
) -> PermutationResult | None:
    """MC primitive, exposed separately for calibration tests; scans use the hybrid selector."""
    return _permutation_test(x, y, lag=lag, seed=seed, n_perm=n_perm, mode="mc")


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    values = np.asarray(p_values, dtype=float)
    if not np.all(np.isfinite(values) & (values >= 0) & (values <= 1)):
        raise ValueError("p-values must be finite and in [0, 1]")
    if not len(values):
        return []
    order = np.argsort(values, kind="stable")
    adjusted = np.minimum.accumulate(
        (values[order] * len(values) / np.arange(1, len(values) + 1))[::-1]
    )[::-1]
    result = np.empty_like(values)
    result[order] = np.minimum(adjusted, 1)
    return [float(value) for value in result]


def _candidates(panel: DailyPanel) -> dict[str, FloatArray]:
    return {
        name: values
        for name, values in panel.exposures.items()
        if np.count_nonzero(values == 1) >= MIN_GROUP and np.count_nonzero(values == 0) >= MIN_GROUP
    }


def _correlation(a: FloatArray, b: FloatArray) -> float | None:
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < MIN_PAIRS:
        return None
    aa, bb = a[mask], b[mask]
    if np.ptp(aa) == 0 or np.ptp(bb) == 0:
        return None
    return float(np.corrcoef(aa, bb)[0, 1])


def find_confounder(panel: DailyPanel, exposure: str, outcome: str, lag: int) -> str | None:
    x = panel.exposures[exposure]
    y = panel.outcomes[outcome][lag:]
    xx = x[:-lag] if lag else x
    candidates = _candidates(panel)
    if panel.sleep_hours is not None:
        candidates["sleep_hours"] = panel.sleep_hours
    scores: list[tuple[float, str]] = []
    for name, c in candidates.items():
        if name == exposure:
            continue
        cc = c[:-lag] if lag else c
        r_cx = _correlation(cc, xx)
        cy = [_correlation(cc, y), _correlation(c[lag:], y)]
        r_cy = max((abs(value) for value in cy if value is not None), default=0.0)
        if r_cx is not None and abs(r_cx) >= CONFOUNDER_R and r_cy >= CONFOUNDER_R:
            scores.append((min(abs(r_cx), r_cy), name))
    return min(scores, key=lambda item: (-item[0], item[1]))[1] if scores else None


def _pattern(panel: DailyPanel, test: ScanTest) -> Pattern:
    result = test.result
    assert test.p_adj is not None and result.p_value is not None
    x, y = panel.exposures[test.exposure], panel.outcomes[test.outcome]
    points = tuple(
        EvidencePoint(
            panel.dates[i], panel.dates[i - test.lag], float(x[i - test.lag]), float(y[i])
        )
        for i in range(test.lag, len(y))
        if np.isfinite(x[i - test.lag]) and np.isfinite(y[i])
    )
    moderate = (
        test.p_adj <= MODERATE_Q
        and abs(result.effect) >= MODERATE_EFFECT
        and result.n_pairs >= MODERATE_MIN_PAIRS
    )
    return Pattern(
        f"{test.exposure}|{test.outcome}|{test.lag}",
        test.exposure,
        test.outcome,
        test.lag,
        result.effect,
        result.p_value,
        test.p_adj,
        "moderate" if moderate else "weak",
        result.n_pairs,
        result.n_exposed,
        result.n_unexposed,
        result.perm_mode,
        result.n_valid,
        find_confounder(panel, test.exposure, test.outcome, test.lag),
        panel.dates[0],
        panel.dates[-1],
        points,
    )


def scan_patterns(
    panel: DailyPanel, *, user_id: str, purpose: str, n_perm: int = N_PERM
) -> ScanResult:
    tests: list[ScanTest] = []
    for exposure, values in sorted(_candidates(panel).items()):
        for outcome, ratings in sorted(panel.outcomes.items()):
            for lag in LAGS:
                seed = derive_seed(user_id, exposure, outcome, str(lag), purpose)
                result = block_permutation_test(values, ratings, lag=lag, seed=seed, n_perm=n_perm)
                if result is not None:
                    tests.append(ScanTest(exposure, outcome, lag, result))
    stable_indices = [
        i for i, test in enumerate(tests) if test.result.stable and test.result.p_value is not None
    ]
    p_values: list[float] = []
    for i in stable_indices:
        p_value = tests[i].result.p_value
        assert p_value is not None
        p_values.append(p_value)
    for index, adjusted in zip(stable_indices, benjamini_hochberg(p_values), strict=True):
        tests[index] = replace(tests[index], p_adj=adjusted)
    reported = [
        _pattern(panel, test)
        for test in tests
        if test.p_adj is not None and test.p_adj <= FDR_Q and abs(test.result.effect) >= MIN_EFFECT
    ]
    reported.sort(key=lambda item: (item.p_adj, -abs(item.effect), item.pattern_key))
    return ScanResult(tuple(reported[:MAX_PATTERNS_STORED]), tuple(tests))

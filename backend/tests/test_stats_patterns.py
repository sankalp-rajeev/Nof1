import ast
import itertools
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from app.stats import patterns
from app.stats.config import BLOCK_LEN, N_PERM, N_PERM_FAST
from app.stats.panel import DailyPanel

pytestmark = pytest.mark.p2


def panel_for(x: np.ndarray, y: np.ndarray) -> DailyPanel:
    return DailyPanel(
        tuple(date(2026, 1, 1) + timedelta(days=i) for i in range(len(x))),
        {"fog": y},
        {"coffee": x},
    )


def reference_enumeration(x: np.ndarray, y: np.ndarray, lag: int = 0) -> tuple[float, int]:
    n_blocks = len(x) // BLOCK_LEN
    base_x = x[:-lag] if lag else x
    base_y = y[lag:]
    mask = np.isfinite(base_x) & np.isfinite(base_y)
    observed = float(np.mean(base_y[mask & (base_x == 1)]) - np.mean(base_y[mask & (base_x == 0)]))
    valid = extreme = 0
    for ordering in itertools.permutations(range(n_blocks)):
        permuted = np.concatenate(
            [*(x[i * BLOCK_LEN : (i + 1) * BLOCK_LEN] for i in ordering), x[n_blocks * BLOCK_LEN :]]
        )
        px = permuted[:-lag] if lag else permuted
        use = np.isfinite(px) & np.isfinite(base_y)
        exposed, unexposed = use & (px == 1), use & (px == 0)
        if use.sum() < 14 or exposed.sum() < 5 or unexposed.sum() < 5:
            continue
        effect = float(base_y[exposed].mean() - base_y[unexposed].mean())
        valid += 1
        extreme += abs(effect) >= abs(observed)
    return extreme / valid, valid


def test_exact_five_block_enumeration_and_fixed_tail() -> None:
    x = np.repeat([0.0, 1.0, 0.0, 1.0, 1.0], BLOCK_LEN)
    x = np.concatenate([x, [0.0, 1.0]])
    y = np.array([2, 1, 3, 4, 8, 6, 7, 5, 3, 2, 4, 1, 7, 6, 9, 8, 6, 5, 7, 4, 2, 8], dtype=float)
    expected, n_valid = reference_enumeration(x, y)
    result = patterns.block_permutation_test(x, y, lag=0, seed=3, n_perm=N_PERM_FAST)
    assert result is not None
    assert result.perm_mode == "exact"
    assert result.n_valid == n_valid == 120
    assert result.p_value == expected


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_mc_converges_to_six_block_enumeration(seed: int) -> None:
    x = np.repeat([0.0, 1.0, 0.0, 1.0, 1.0, 0.0], BLOCK_LEN)
    y = np.array(
        [1, 3, 2, 4, 7, 5, 6, 8, 5, 1, 2, 3, 8, 4, 5, 6, 2, 4, 7, 6, 3, 6, 2, 5], dtype=float
    )
    exact, n_valid = reference_enumeration(x, y)
    assert n_valid == 720 and 0 < exact < 1
    result = patterns.monte_carlo_test(x, y, lag=0, seed=seed, n_perm=2000)
    assert result is not None and result.p_value is not None
    tolerance = 3 * math.sqrt(exact * (1 - exact) / 2000) + 1 / 2000
    assert abs(result.p_value - exact) <= tolerance
    assert result.perm_mode == "mc" and result.n_valid == 2000


@pytest.mark.parametrize("budget", [N_PERM_FAST, N_PERM])
def test_mode_selection_at_factorial_threshold(budget: int) -> None:
    for blocks in (5, 6, 7):
        assert patterns.permutation_mode(blocks, budget) == (
            "exact" if math.factorial(blocks) <= budget else "mc"
        )
        threshold = math.factorial(blocks)
        assert patterns.permutation_mode(blocks, threshold) == "exact"
        assert patterns.permutation_mode(blocks, threshold - 1) == "mc"


def test_bh_matches_hand_calculated_reference() -> None:
    assert patterns.benjamini_hochberg([0.01, 0.04, 0.03, 0.002]) == pytest.approx(
        [0.02, 0.04, 0.04, 0.008]
    )
    assert patterns.benjamini_hochberg([]) == []


@pytest.mark.parametrize("length", [0, 13, 19])
def test_scan_rejects_insufficient_data_and_full_blocks(length: int) -> None:
    x = np.arange(length, dtype=float) % 2
    result = patterns.scan_patterns(
        panel_for(x, 2 + 4 * x), user_id="guard", purpose="p2", n_perm=N_PERM_FAST
    )
    assert result.patterns == () and result.tests == ()


def test_lag_alignment_recovers_large_effect_and_snapshot() -> None:
    rng = np.random.default_rng(4)
    x = rng.binomial(1, 0.5, size=60).astype(float)
    y = np.full(60, 5.0)
    y[2:] = 2 + 5 * x[:-2]
    result = patterns.scan_patterns(
        panel_for(x, y), user_id="lag", purpose="p2", n_perm=N_PERM_FAST
    )
    hit = next(item for item in result.patterns if item.lag_days == 2)
    assert hit.effect == 5 and hit.tier == "moderate"
    assert hit.n_pairs == 58 and hit.n_valid == N_PERM_FAST and hit.perm_mode == "mc"
    assert all(
        point.outcome_date - point.exposure_date == timedelta(days=2) for point in hit.data_points
    )
    assert hit.data_points[0].x == x[0] and hit.data_points[0].y == y[2]
    assert result == patterns.scan_patterns(
        panel_for(x, y), user_id="lag", purpose="p2", n_perm=N_PERM_FAST
    )


def test_two_hundred_seeded_null_series_flag_share() -> None:
    flagged = 0
    for seed in range(200):
        rng = np.random.default_rng(seed)
        x = rng.binomial(1, 0.5, size=60).astype(float)
        y = np.rint(np.clip(rng.normal(5, 1.5, size=60), 0, 10))
        result = patterns.scan_patterns(
            panel_for(x, y), user_id=f"null-{seed}", purpose="p2", n_perm=N_PERM_FAST
        )
        flagged += bool(result.patterns)
    assert flagged / 200 <= 0.15


def sparse_series() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.zeros(20)
    x[:4] = 1
    x[6] = 1
    y = np.concatenate([np.arange(14, dtype=float) % 11, np.full(6, np.nan)])
    empty_group_order = np.array([2, 3, 4, 1, 0])
    return x, y, empty_group_order


@pytest.mark.parametrize("valid_count,stable", [(5, True), (3, False)])
def test_mc_redraws_empty_groups_uses_valid_denominator_and_stability(
    monkeypatch: pytest.MonkeyPatch, valid_count: int, stable: bool
) -> None:
    x, y, invalid = sparse_series()
    orders = [np.arange(5)] * valid_count + [invalid] * (40 - valid_count)
    position = 0

    def scripted_orders(rng: np.random.Generator, blocks: int, count: int) -> np.ndarray:
        nonlocal position
        batch = np.array(orders[position : position + count])
        position += count
        return batch

    monkeypatch.setattr(patterns, "_draw_block_orders", scripted_orders)
    result = patterns.monte_carlo_test(x, y, lag=0, seed=0, n_perm=8)
    assert result is not None
    assert result.n_valid == valid_count and result.n_draws == 40
    assert result.p_value == 1
    assert result.stable is stable


def test_exact_stability_uses_total_orderings_not_requested_budget() -> None:
    x, y, _ = sparse_series()
    _, n_valid = reference_enumeration(x, y)
    result = patterns.block_permutation_test(x, y, lag=0, seed=0, n_perm=N_PERM)
    assert result is not None
    assert result.n_valid == n_valid == 36
    assert result.perm_mode == "exact" and not result.stable


def test_unstable_tests_are_excluded_from_bh(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []
    original = patterns.benjamini_hochberg

    def record_bh(values: list[float]) -> list[float]:
        seen.extend(values)
        return original(values)

    def scripted_test(
        x: np.ndarray, y: np.ndarray, *, lag: int, seed: int, n_perm: int
    ) -> patterns.PermutationResult:
        return patterns.PermutationResult(
            effect=2,
            n_pairs=60,
            n_exposed=30,
            n_unexposed=30,
            p_value=[0.001, 0.2, 0.0001][lag],
            perm_mode="mc",
            n_valid=500 if lag < 2 else 3,
            n_draws=500,
            stable=lag < 2,
        )

    monkeypatch.setattr(patterns, "benjamini_hochberg", record_bh)
    monkeypatch.setattr(patterns, "block_permutation_test", scripted_test)
    x = np.arange(60, dtype=float) % 2
    result = patterns.scan_patterns(
        panel_for(x, 3 + 2 * x), user_id="stable", purpose="p2", n_perm=N_PERM_FAST
    )
    assert seen == [0.001, 0.2]
    assert [item.lag_days for item in result.patterns] == [0]


def test_confounder_uses_exposure_alignment_and_name_tie_break() -> None:
    rng = np.random.default_rng(5)
    c = rng.binomial(1, 0.5, 60).astype(float)
    y = np.full(60, np.nan)
    y[2:] = 3 + 4 * c[:-2]
    panel = panel_for(c, y)
    panel.exposures["zeta"] = c.copy()
    panel.exposures["alpha"] = c.copy()
    assert patterns.find_confounder(panel, "coffee", "fog", 2) == "alpha"
    panel.exposures.pop("alpha")
    panel.exposures.pop("zeta")
    assert patterns.find_confounder(panel, "coffee", "fog", 2) is None


def test_stats_imports_are_pure_and_rng_always_has_a_seed() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "stats"
    forbidden = ("app.db", "app.agent", "app.api", "socket", "http", "urllib", "requests")
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
            assert not any(name.startswith(forbidden) for name in names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "default_rng":
                    assert node.args or node.keywords, path


def test_hybrid_selector_uses_exact_for_six_blocks_at_report_budget() -> None:
    x = np.repeat([0.0, 1.0, 0.0, 1.0, 1.0, 0.0], BLOCK_LEN)
    y = 2 + 4 * x
    fast = patterns.block_permutation_test(x, y, lag=0, seed=0, n_perm=N_PERM_FAST)
    full = patterns.block_permutation_test(x, y, lag=0, seed=0, n_perm=N_PERM)
    assert fast is not None and full is not None
    assert fast.perm_mode == "mc" and fast.n_valid == 500
    assert full.perm_mode == "exact" and full.n_valid == 720


def test_confounder_checks_current_day_outcome_alignment() -> None:
    x = np.random.default_rng(6).binomial(1, 0.5, 60).astype(float)
    panel = panel_for(x, 3 + 4 * x)
    panel.exposures["current"] = x.copy()
    assert patterns.find_confounder(panel, "coffee", "fog", 2) == "current"


def test_pattern_limit_ranking_and_snapshot_survive_input_edits() -> None:
    x = np.random.default_rng(7).binomial(1, 0.5, 60).astype(float)
    y = 2 + 4 * x
    panel = panel_for(x, y)
    panel.exposures.clear()
    panel.exposures.update({name: x.copy() for name in "abcdef"})
    result = patterns.scan_patterns(panel, user_id="ranking", purpose="p2", n_perm=N_PERM_FAST)
    assert [item.exposure for item in result.patterns] == list("abcde")
    assert all(item.lag_days == 0 for item in result.patterns)
    saved = result.patterns[0].data_points[0].y
    y[0] = 10
    assert result.patterns[0].data_points[0].y == saved

from pathlib import Path

import pytest

from app.stats.config import N_PERM_FAST
from sim.demo import DEMO_SEED, demo_world
from sim.report import EvaluationReport, write_initial_baseline
from sim.runner import evaluate_suite, run_scan
from sim.world import world_to_panel

pytestmark = pytest.mark.p3


@pytest.fixture(scope="module")
def gate_report() -> EvaluationReport:
    return evaluate_suite(n_perm=N_PERM_FAST, include_power=False, include_verdicts=False)


def test_e1_null_pattern_rate(gate_report: EvaluationReport) -> None:
    assert gate_report.e1.value is not None and gate_report.e1.value <= 0.15


def test_e2_large_effect_recall(gate_report: EvaluationReport) -> None:
    assert gate_report.e2.value is not None and gate_report.e2.value >= 0.85


def test_e3_null_verdict_rate(gate_report: EvaluationReport) -> None:
    assert gate_report.e3.value is not None and gate_report.e3.value <= 0.10


def test_demo_seed_is_first_qualifying_seed_and_has_matching_pattern() -> None:
    world = demo_world()
    assert world.truth.seed == DEMO_SEED
    (effect,) = world.truth.effects
    assert world.truth.patient_type == "single_effect" and effect.beta == -3 and effect.lag == 0
    assert len(world.days) == 45
    patterns = run_scan(world_to_panel(world), identity=f"demo-{DEMO_SEED}", n_perm=2000).patterns
    assert any(p.exposure == effect.exposure and p.lag_days == 0 and p.effect < 0 for p in patterns)


def test_report_schema_and_one_time_baseline_creation(
    gate_report: EvaluationReport, tmp_path: Path
) -> None:
    payload = gate_report.to_dict()
    assert payload["schema_version"] == 1
    assert payload["n_perm"] == N_PERM_FAST
    assert payload["cohorts"]["A"]["n"] == 1000 and payload["cohorts"]["N"]["n"] == 300
    assert {"E1", "E1c", "E1s", "E2", "E2b", "E3", "E3b"} <= set(payload["metrics"])
    target = tmp_path / "baseline.json"
    write_initial_baseline(target, {"stats": {"E1": 0.1, "E2": 0.9, "E3": 0.05}}, revision="test")
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        write_initial_baseline(target, {"stats": {"E1": 0, "E2": 1, "E3": 0}}, revision="changed")
    assert target.read_bytes() == original


def test_verdict_matrix_reports_all_four_labels_including_zero_counts() -> None:
    report = evaluate_suite(
        n_perm=N_PERM_FAST,
        include_power=False,
        include_verdicts=True,
        scan_seeds=[0],
        null_seeds=[2000],
    )
    assert len(report.e3b) == 8
    for cell in report.e3b.values():
        assert set(cell.counts) == {"helped", "worsened", "no_detectable_effect", "inconclusive"}
        assert sum(cell.counts.values()) == cell.n == 100

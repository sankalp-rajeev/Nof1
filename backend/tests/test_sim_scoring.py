import ast
from dataclasses import replace
from pathlib import Path

import pytest

from sim.scoring import Claim, compare_absolute_gates, compare_regression, score_patterns
from sim.world import PlantedEffect, generate_world

pytestmark = pytest.mark.p3


def test_hit_rule_is_one_to_one_and_checks_sign_and_lag() -> None:
    truth = replace(
        generate_world(0, days=1).truth,
        patient_type="single_effect",
        effects=(PlantedEffect("coffee", "fatigue", 1, -3),),
    )
    hit = Claim("coffee", "fatigue", 1, -2)
    result = score_patterns(truth, [hit, hit])
    assert result.hits == (True,) and result.false_positives == 1
    for miss in [replace(hit, effect=2), replace(hit, lag_days=0), replace(hit, outcome="other")]:
        result = score_patterns(truth, [miss])
        assert result.hits == (False,) and result.false_positives == 1


def test_short_sleep_is_not_a_null_false_positive_or_planted_hit() -> None:
    truth = replace(generate_world(0, days=1).truth, patient_type="null", effects=())
    result = score_patterns(truth, [Claim("short_sleep", "fatigue", 0, 2)])
    assert not result.null_flag and result.false_positives == 0 and result.short_sleep
    truth = replace(
        truth, patient_type="single_effect", effects=(PlantedEffect("coffee", "fatigue", 0, 3),)
    )
    assert score_patterns(truth, [Claim("short_sleep", "fatigue", 0, 3)]).hits == (False,)


def test_confounder_scoring_separates_flagged_and_unflagged_reports() -> None:
    truth = replace(
        generate_world(0, days=1).truth,
        patient_type="confounded_null",
        effects=(),
        confounded_exposure="coffee",
    )
    flagged = score_patterns(truth, [Claim("coffee", "fatigue", 0, 2, "sleep_hours")])
    assert (
        flagged.confounded_any and flagged.confounded_flagged and not flagged.confounded_unflagged
    )
    unflagged = score_patterns(truth, [Claim("coffee", "fatigue", 0, 2)])
    assert (
        unflagged.confounded_any
        and unflagged.confounded_unflagged
        and not unflagged.confounded_flagged
    )


def test_regression_comparator_rejects_degradation_and_ignores_absent_components() -> None:
    baseline = {"stats": {"E1": 0.04, "E2": 0.8, "E3": 0.02}, "safety": {"E5": 1.0}}
    assert compare_regression({"stats": {"E1": 0.04, "E2": 0.8, "E3": 0.02}}, baseline) == []
    issues = compare_regression({"stats": {"E1": 0.08, "E2": 0.74, "E3": 0.06}}, baseline)
    assert len(issues) == 3


def test_scoring_has_no_database_llm_or_network_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "sim" / "scoring.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = (
        "app.db",
        "app.agent",
        "app.api",
        "sqlalchemy",
        "socket",
        "http",
        "urllib",
        "requests",
        "openai",
        "google",
    )
    for node in ast.walk(tree):
        names = (
            [item.name for item in node.names]
            if isinstance(node, ast.Import)
            else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
        )
        assert not any(name.startswith(forbidden) for name in names)


@pytest.mark.parametrize("metric,value", [("E1", 0.150001), ("E2", 0.849999), ("E3", 0.100001)])
def test_absolute_gates_fail_even_with_zero_relative_drift(metric: str, value: float) -> None:
    metrics = {"E1": 0.10, "E2": 0.90, "E3": 0.05}
    metrics[metric] = value
    current = {"stats": metrics}
    assert compare_regression(current, current) == []
    issues = compare_absolute_gates(current)
    assert len(issues) == 1 and metric in issues[0]


def test_absolute_gate_boundaries_pass_and_absent_components_are_ignored() -> None:
    assert compare_absolute_gates({"stats": {"E1": 0.15, "E2": 0.85, "E3": 0.10}}) == []
    assert compare_absolute_gates({}) == []

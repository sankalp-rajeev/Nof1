import inspect
from collections import Counter
from dataclasses import asdict
from datetime import timedelta

import numpy as np
import pytest

from app.stats.experiment import make_protocol, schedule
from sim.runner import run_scan
from sim.world import EXPOSURES, generate_world, simulate_experiment, world_to_panel

pytestmark = pytest.mark.p3


def test_seed_determinism_prefixes_and_no_ground_truth_in_runner_input() -> None:
    first = generate_world(7)
    assert first == generate_world(7)
    assert first.days[:30] == generate_world(7, days=30).days
    panel = world_to_panel(first)
    assert set(asdict(panel)) == {"dates", "outcomes", "exposures", "sleep_hours"}
    assert "truth" not in inspect.signature(run_scan).parameters
    assert set(panel.exposures) == set(EXPOSURES) | {"short_sleep"}
    assert all(not hasattr(values, "truth") for values in panel.exposures.values())


def test_patient_type_mix_over_prescribed_dev_cohort() -> None:
    counts = Counter(generate_world(seed, days=1).truth.patient_type for seed in range(1000))
    for name, probability in {
        "null": 0.4,
        "single_effect": 0.4,
        "double_effect": 0.1,
        "confounded_null": 0.1,
    }.items():
        assert abs(counts[name] / 1000 - probability) <= 0.04


def test_exposure_autocorrelation_and_missingness_stationarity() -> None:
    world = generate_world(11, days=50000, patient_type="null")
    matrix = np.array([day.exposures for day in world.days[200:]])
    for column, target in enumerate(world.truth.stickiness):
        actual = np.corrcoef(matrix[:-1, column], matrix[1:, column])[0, 1]
        assert abs(actual - target) <= 0.03
    missing_rate = np.mean([not day.observed for day in world.days[200:]])
    assert abs(missing_rate - world.truth.p_miss) <= 0.02


def test_checklist_noise_changes_reports_without_changing_physical_world() -> None:
    clean = generate_world(3, checklist_error=0)
    flipped = generate_world(3, checklist_error=1)
    for a, b in zip(clean.days, flipped.days, strict=True):
        assert (a.exposures, a.y, a.sleep_hours, a.observed) == (
            b.exposures,
            b.y,
            b.sleep_hours,
            b.observed,
        )
        assert b.reported_exposures == tuple(1 - value for value in a.exposures)


def test_experiment_continues_world_and_forces_adherent_exposure() -> None:
    world = generate_world(9)
    protocol = make_protocol(
        "sim-9",
        "experiment",
        exposure="walk",
        outcome="fatigue",
        start_date=world.days[-1].date + timedelta(days=1),
    )
    experiment = simulate_experiment(world, protocol, adherence_p=1)
    assert experiment == simulate_experiment(world, protocol, adherence_p=1)
    assert len(experiment.days) == len(experiment.observations) == 14
    column = EXPOSURES.index("walk")
    for day, observation, plan in zip(
        experiment.days, experiment.observations, schedule(protocol), strict=True
    ):
        assert day.date == plan.date
        if plan.phase != "baseline":
            assert day.exposures[column] == int(plan.phase == "on")
            assert observation.adherence is (True if day.observed else None)
        assert observation.y == (day.y if day.observed else None)


def test_held_out_seeds_are_rejected_before_world_generation() -> None:
    with pytest.raises(ValueError, match="dev"):
        generate_world(10000)

import sys
from types import SimpleNamespace

import pytest

from app.stats.config import N_PERM_FAST
from sim import cli
from sim.report import Rate

pytestmark = pytest.mark.p3


def test_cli_uses_full_cohorts_for_absolute_gates_and_subsets_for_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subset = {"stats": {"E1": 0.136, "E2": 0.70, "E3": 0.14}}
    full = SimpleNamespace(e1=Rate(4, 100), e2=Rate(9, 10), e3=Rate(8, 100))
    calls: list[dict[str, object]] = []

    def evaluate(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return full

    monkeypatch.setattr(sys, "argv", ["sim", "regression"])
    monkeypatch.setattr(cli, "regression_components", lambda: subset)
    monkeypatch.setattr(cli, "read_baseline", lambda path: subset)
    monkeypatch.setattr(cli, "evaluate_suite", evaluate)
    assert cli.main() == 0
    assert calls == [{"n_perm": N_PERM_FAST, "include_power": False, "include_verdicts": False}]
    full.e2 = Rate(8, 10)
    assert cli.main() == 1

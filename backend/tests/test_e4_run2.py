"""Fresh E4 run-2 authorization, with no network or generation calls."""

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agent.llm.cost import PriceBook
from app.config import Settings
from sim.chat_cli import main
from sim.live_limits import LiveLimits

pytestmark = pytest.mark.p8


def test_run2_budget_does_not_raise_existing_authorization(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LiveLimits(PriceBook({}), tmp_path / "old.json", cap=Decimal("2.00"))
    with pytest.raises(ValueError):
        LiveLimits(PriceBook({}), tmp_path / "too-high.json", cap=Decimal("2.01"), e4_run2=True)
    with pytest.raises(ValueError):
        LiveLimits(PriceBook({}), tmp_path / "too-many.json", max_calls=5001, e4_run2=True)


@pytest.mark.parametrize("extra", [[], ["--e4-only", "--patients", "1"]])
def test_run2_rejects_other_scopes(extra: list[str]) -> None:
    with pytest.raises(ValueError, match="full 30-patient"):
        main(["live", "--budget", "2.00", "--e4-run2", *extra])


def test_run2_fresh_full_cohort_and_exclusive_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_CLASS", "synthetic")
    original = tmp_path / "authorized-e4"
    original.mkdir()
    evidence = original / "STARTED.json"
    evidence.write_text('{"run":1}')
    monkeypatch.setattr("sim.chat_cli.authorization_claim", lambda **_: original)
    settings = Settings(_env_file=None, sim_persona="ollama:gemma3:12b")
    monkeypatch.setattr("sim.chat_cli.live_settings", lambda *_: settings)
    monkeypatch.setattr("sim.chat_cli.create_db_engine", lambda _: MagicMock())
    calls = []

    def cohort(*args: object, **kwargs: object) -> tuple[dict[str, object], None]:
        assert kwargs["seeds"] == range(30)
        assert kwargs["days"] == 30
        assert kwargs["include_e7"] is False
        limits = kwargs["limits"]
        assert isinstance(limits, LiveLimits)
        assert limits.cap == Decimal("2.00")
        assert limits.max_calls == 5000
        assert limits.summary()["actual_calls"] == 0
        calls.append(True)
        return {"stopped": None, "E7": {"failed": []}}, None

    monkeypatch.setattr("sim.chat_cli.run_chat", cohort)
    output = tmp_path / "run2"
    args = ["live", "--budget", "2.00", "--e4-only", "--e4-run2"]
    assert main([*args, "--output", str(output)]) == 0
    assert json.loads((output / "ledger.json").read_text())["actual_calls"] == 0
    with pytest.raises(FileExistsError):
        main([*args, "--output", str(tmp_path / "repeat")])
    assert calls == [True]
    assert evidence.read_text() == '{"run":1}'

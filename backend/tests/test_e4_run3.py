"""Run-3 authorization is separate, bounded and one-shot; no generation."""

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from sim.chat_cli import main
from sim.live_limits import LiveLimits

pytestmark = pytest.mark.p8


@pytest.mark.parametrize(
    "args",
    [
        ["--e4-run3"],
        ["--e4-only", "--e4-run3", "--patients", "29"],
        ["--e4-only", "--e4-run3", "--days", "29"],
        ["--e4-only", "--e4-run3", "--budget", "2.01"],
        ["--e4-only", "--e4-run3", "--max-calls", "5001"],
        ["--e4-only", "--e4-run2", "--e4-run3"],
    ],
)
def test_run3_rejects_other_scopes_and_limits(args: list[str]) -> None:
    with pytest.raises(ValueError):
        main(["live", "--budget", "2.00", *args])


def test_run3_has_exclusive_claim_and_preserves_runs_1_and_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_CLASS", "synthetic")
    original = tmp_path / "authorized-e4"
    prior = [original, original.with_name(original.name + "-run-2")]
    for index, path in enumerate(prior, 1):
        path.mkdir()
        (path / "STARTED.json").write_text(json.dumps({"run": index}))
    frozen = {path: (path / "STARTED.json").read_bytes() for path in prior}
    monkeypatch.setattr("sim.chat_cli.authorization_claim", lambda **_: original)
    settings = Settings(_env_file=None, sim_persona="ollama:gemma3:12b")
    monkeypatch.setattr("sim.chat_cli.live_settings", lambda *_: settings)
    monkeypatch.setattr("sim.chat_cli.create_db_engine", lambda _: MagicMock())
    calls: list[bool] = []

    def cohort(*args: object, **kwargs: object) -> tuple[dict[str, object], None]:
        assert kwargs["seeds"] == range(30) and kwargs["days"] == 30
        assert kwargs["include_e7"] is False and kwargs["warmup_persona_enabled"] is True
        limits = kwargs["limits"]
        assert isinstance(limits, LiveLimits)
        assert limits.cap == Decimal("2.00") and limits.max_calls == 5000
        assert limits.summary()["actual_calls"] == 0
        calls.append(True)
        return {"stopped": None, "E7": {"failed": []}}, None

    monkeypatch.setattr("sim.chat_cli.run_chat", cohort)
    output = tmp_path / "run3"
    args = ["live", "--budget", "2.00", "--e4-only", "--e4-run3"]
    assert main([*args, "--output", str(output)]) == 0
    assert json.loads((output / "configuration.json").read_text())["e4_run"] == 3
    marker = original.with_name(original.name + "-run-3") / "STARTED.json"
    frozen_marker = marker.read_bytes()
    for flags in (["--e4-run3"], ["--e4-run2"], []):
        with pytest.raises(FileExistsError):
            main(
                [
                    "live",
                    "--budget",
                    "1.00",
                    "--e4-only",
                    *flags,
                    "--output",
                    str(tmp_path / "different-output"),
                ]
            )
    assert calls == [True] and not (tmp_path / "different-output").exists()
    assert marker.read_bytes() == frozen_marker
    assert all((path / "STARTED.json").read_bytes() == data for path, data in frozen.items())

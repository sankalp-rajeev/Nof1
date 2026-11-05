"""Run 4 has a fresh one-shot claim and refuses low VRAM before consuming it."""

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agent.llm.base import ProviderError
from app.config import Settings
from sim.chat_cli import main
from sim.live_limits import LiveLimits

pytestmark = pytest.mark.p8


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--e4-only", "--patients", "29"],
        ["--e4-only", "--days", "29"],
        ["--e4-only", "--budget", "2.01"],
        ["--e4-only", "--max-calls", "5001"],
        ["--e4-only", "--e4-run2"],
        ["--e4-only", "--e4-run3"],
    ],
)
def test_run4_rejects_invalid_scope_limits_and_combined_authorizations(extra: list[str]) -> None:
    with pytest.raises(ValueError):
        main(["live", "--budget", "2.00", "--e4-run4", *extra])


def prepare_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DATA_CLASS", "synthetic")
    claim = tmp_path / "authorized-e4"
    monkeypatch.setattr("sim.chat_cli.authorization_claim", lambda **_: claim)
    monkeypatch.setattr(
        "sim.chat_cli.live_settings",
        lambda *_: Settings(_env_file=None, sim_persona="ollama:gemma3:12b"),
    )
    return claim


def test_low_vram_refusal_does_not_claim_create_output_or_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    claim = prepare_cli(tmp_path, monkeypatch)

    def refuse() -> int:
        raise ProviderError("gpu_preflight_vram: 1866 MiB free; require 10240 MiB")

    monkeypatch.setattr("sim.chat_cli.require_free_vram", refuse)
    monkeypatch.setattr(
        "sim.chat_cli.create_db_engine", lambda _: pytest.fail("No DB before check")
    )
    monkeypatch.setattr("sim.chat_cli.run_chat", lambda *_a, **_k: pytest.fail("No generation"))
    output = tmp_path / "output"
    assert (
        main(["live", "--budget", "2.00", "--e4-only", "--e4-run4", "--output", str(output)]) == 1
    )
    assert "1866 MiB" in capsys.readouterr().out
    assert not output.exists() and not claim.with_name(claim.name + "-run-4").exists()


def test_run4_cannot_repeat_with_another_output_and_preserves_prior_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claim = prepare_cli(tmp_path, monkeypatch)
    prior = [claim, *(claim.with_name(claim.name + suffix) for suffix in ("-run-2", "-run-3"))]
    for index, path in enumerate(prior, 1):
        path.mkdir()
        (path / "STARTED.json").write_text(json.dumps({"run": index}))
    snapshots = {path: (path / "STARTED.json").read_bytes() for path in prior}
    monkeypatch.setattr("sim.chat_cli.require_free_vram", lambda: 11000)
    monkeypatch.setattr("sim.chat_cli.create_db_engine", lambda _: MagicMock())
    dispatched: list[bool] = []

    def cohort(*_args: object, **kwargs: object) -> tuple[dict[str, object], None]:
        assert kwargs["seeds"] == range(30) and kwargs["days"] == 30
        assert kwargs["include_e7"] is False and kwargs["warmup_persona_enabled"] is True
        limits = kwargs["limits"]
        assert isinstance(limits, LiveLimits)
        assert limits.cap == Decimal("2.00") and limits.max_calls == 5000
        dispatched.append(True)
        return {"stopped": None, "E7": {"failed": []}}, None

    monkeypatch.setattr("sim.chat_cli.run_chat", cohort)
    args = ["live", "--budget", "2.00", "--e4-only", "--e4-run4"]
    output = tmp_path / "output"
    assert main([*args, "--output", str(output)]) == 0
    configuration = json.loads((output / "configuration.json").read_text())
    assert configuration["e4_run"] == 4 and configuration["free_vram_mib_before_warmup"] == 11000
    marker = claim.with_name(claim.name + "-run-4") / "STARTED.json"
    marker_bytes = marker.read_bytes()
    with pytest.raises(FileExistsError):
        main([*args, "--output", str(tmp_path / "different-output")])
    assert dispatched == [True] and marker.read_bytes() == marker_bytes
    assert not (tmp_path / "different-output").exists()
    assert all((path / "STARTED.json").read_bytes() == value for path, value in snapshots.items())

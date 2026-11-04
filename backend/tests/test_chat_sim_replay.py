"""Offline replay contracts and command safeguards; never execute held-out worlds."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from app.agent.analyzer import TurnAnalysis, analyze
from app.agent.llm.base import CallContext, LLMMessage, LLMResponse
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.tracing import MemoryTraceStore
from app.config import ROOT, Settings
from sim.chat_cli import family, main, require_budget
from sim.extraction import ExtractionScore
from sim.final import main as final_main
from sim.final_scope import FINAL_SEEDS_ALLOWED
from sim.replay import (
    RecordingClient,
    ReplayBundle,
    replay_bundle,
    replay_regression,
)

pytestmark = pytest.mark.p8
FIXTURE = ROOT / "evals/fixtures/chat/handwritten.json"


def test_handwritten_replay_reproduces_hand_counted_scores_exactly_twice() -> None:
    fixture = ReplayBundle.model_validate_json(FIXTURE.read_bytes())
    assert fixture.provenance == "handwritten_offline"
    assert replay_bundle(fixture) == ExtractionScore(5, 3, 2)
    assert replay_bundle(fixture) == ExtractionScore(5, 3, 2)
    assert replay_regression() == []


def test_replay_rejects_metric_drift_and_missing_fixtures(tmp_path: Path) -> None:
    fixture = ReplayBundle.model_validate_json(FIXTURE.read_bytes())
    with pytest.raises(ValueError, match="aggregate drift"):
        replay_bundle(fixture.model_copy(update={"expected": ExtractionScore()}))
    assert replay_regression(tmp_path) == ["P8 replay fixtures are missing"]


def test_analyzer_accepts_explicit_numbers_before_sentence_punctuation() -> None:
    fake = FakeLLMClient(
        [
            LLMResponse(
                '{"intent":"checkin","events":[{"kind":"symptom","name":"fatigue","severity":6}]}'
            )
        ]
    )
    router = LLMRouter(
        Settings(_env_file=None, llm_analyzer="ollama:fixture"),
        store=MemoryTraceStore(),
        prices=PriceBook({}),
        clients={"ollama": fake},
    )
    messages = (
        LLMMessage(
            "user",
            json.dumps(
                {"user_text": "fatigue 6.", "tracking": {"outcomes": [{"name": "fatigue"}]}}
            ),
        ),
    )
    result = analyze(router, messages, ctx=CallContext("analyzer", "synthetic", None, UUID(int=1)))
    assert isinstance(result.value, TurnAnalysis)
    assert result.value.events[0].severity == 6


def test_tape_refuses_real_calls_before_reaching_provider() -> None:
    fake = FakeLLMClient()
    client = RecordingClient(fake, [])
    with pytest.raises(ValueError, match="synthetic"):
        client.generate(
            [], max_tokens=10, temperature=0, ctx=CallContext("analyzer", "real", None, UUID(int=1))
        )
    assert not fake.calls


@pytest.mark.parametrize("budget", [None, 0, -1, float("nan"), float("inf")])
def test_budget_refusal_precedes_settings_database_or_providers(budget: float | None) -> None:
    with pytest.raises(ValueError, match="MAX_SPEND_USD"):
        require_budget(budget)


def test_live_and_final_commands_refuse_without_explicit_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAX_SPEND_USD", raising=False)
    with pytest.raises(ValueError, match="MAX_SPEND_USD"):
        main(["live"])
    with pytest.raises(ValueError, match="MAX_SPEND_USD"):
        final_main([])
    assert family("ollama:llama3.2") == family("ollama:llama3.3")
    assert family("ollama:qwen3") != family("gemini:configured")


def test_offline_cli_replay_needs_no_budget_or_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MAX_SPEND_USD", raising=False)
    assert main(["replay", str(FIXTURE)]) == 0
    assert json.loads(capsys.readouterr().out)["extraction"]["tp"] == 5


def test_final_refuses_before_seed_authorization_without_human_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sim.final.phase_approved", lambda _: False)
    with pytest.raises(ValueError, match="Human approval"):
        final_main(["--budget", "0.01"])
    assert FINAL_SEEDS_ALLOWED.get() is False

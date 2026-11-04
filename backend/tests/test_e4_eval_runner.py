"""E4-only authorization and local-persona connectivity, entirely offline."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from openai import OpenAI

from app.agent.llm.cost import PriceBook
from app.agent.llm.openai_compat import OpenAICompatClient
from app.agent.tracing import MemoryTraceStore
from app.config import Settings
from sim.chat_cli import authorization_claim, main
from sim.config import E4_OLLAMA_BASE_URL, E4_PERSONA_TIMEOUT_S
from sim.live_limits import LimitedClient, LimitedRouter, LiveLimits
from sim.replay import RecordingClient

pytestmark = pytest.mark.p8


def test_eval_timeout_changes_only_local_persona_client(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda _: pytest.fail("No network or generation allowed"))
    with httpx.Client(transport=transport) as http:
        sdk = OpenAI(
            api_key="ollama",
            base_url=E4_OLLAMA_BASE_URL,
            timeout=20,
            max_retries=0,
            http_client=http,
        )
        raw = OpenAICompatClient(sdk, "gemma3:12b")
        settings = Settings(_env_file=None, sim_persona="ollama:gemma3:12b")
        router = LimitedRouter(
            settings,
            store=MemoryTraceStore(),
            prices=PriceBook({}),
            clients={"ollama:gemma3:12b": raw},
        )
        router.tape = []
        router.limits = LiveLimits(PriceBook({}), tmp_path / "ledger.json")
        router.persona_timeout_s = E4_PERSONA_TIMEOUT_S
        wrapped = router._client("ollama", "gemma3:12b")
        assert isinstance(wrapped, RecordingClient)
        assert isinstance(wrapped.client, LimitedClient)
        assert isinstance(wrapped.client.client, OpenAICompatClient)
        assert wrapped.client.client.client.timeout == E4_PERSONA_TIMEOUT_S
        assert wrapped.client.client.client.max_retries == 0
        assert sdk.timeout == settings.llm_timeout_s == 20
        assert router.limits.summary()["actual_calls"] == 0
        assert router._client("ollama", "gemma3:12b") is wrapped


def test_separate_authorizations_have_distinct_immutable_claims() -> None:
    assert authorization_claim(e4_only=True) != authorization_claim(e4_only=False)
    assert authorization_claim(e4_only=False).name == "p8-authorized-live-2026-11-04"
    assert authorization_claim(e4_only=True).name == "p8-authorized-e4-2026-11-04"


def test_e4_cli_never_enables_safety_and_cannot_be_repeated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_CLASS", "synthetic")
    original_claim = tmp_path / "original-live"
    original_claim.mkdir()
    (original_claim / "STARTED.json").write_text('{"original":true}')
    e4_claim = tmp_path / "authorized-e4"
    monkeypatch.setattr(
        "sim.chat_cli.authorization_claim",
        lambda *, e4_only: e4_claim if e4_only else original_claim,
    )
    settings = Settings(_env_file=None, sim_persona="ollama:gemma3:12b")
    monkeypatch.setattr("sim.chat_cli.live_settings", lambda *_: settings)
    engine = MagicMock()
    monkeypatch.setattr("sim.chat_cli.create_db_engine", lambda _: engine)
    calls: list[bool] = []

    def cohort(config: Settings, db: object, **kwargs: object) -> tuple[dict[str, object], None]:
        assert kwargs["include_e7"] is False
        assert config.ollama_base_url == E4_OLLAMA_BASE_URL
        assert db is engine
        router = kwargs["router"]
        assert isinstance(router, LimitedRouter)
        assert router.persona_timeout_s == E4_PERSONA_TIMEOUT_S
        assert router.settings.llm_timeout_s == 20
        calls.append(True)
        return {"stopped": None, "E7": {"tested": 0, "failed": [], "pending": True}}, None

    monkeypatch.setattr("sim.chat_cli.run_chat", cohort)
    output = tmp_path / "e4-output"
    args = ["live", "--budget", "1.00", "--max-calls", "5000", "--e4-only"]
    assert main([*args, "--output", str(output)]) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["evaluation_scope"] == "E4_only"
    assert report["safety_cases_enabled"] is False
    assert report["E7"]["tested"] == 0
    assert report["limits"]["actual_calls"] == 0
    with pytest.raises(FileExistsError):
        main([*args, "--output", str(tmp_path / "different-output")])
    assert calls == [True]
    assert (original_claim / "STARTED.json").read_text() == '{"original":true}'

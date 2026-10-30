import ast
import socket
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest_socket import SocketBlockedError
from scripts.gate import frontend_expression, marker_expression

from app.agent.llm.base import CallContext, LLMClient, LLMMessage, LLMResponse
from app.agent.llm.fake import FakeLLMClient
from app.config import Settings
from app.main import app

pytestmark = pytest.mark.p0


def context(purpose: str = "analyzer") -> CallContext:
    return CallContext(purpose, "synthetic", None, UUID(int=1))


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    settings = Settings(_env_file=None)
    assert settings.debug is False
    assert settings.max_total_tokens == 2_000_000
    assert settings.llm_analyzer == "gemini:CHANGE_ME"


@pytest.mark.parametrize("route", ["gemini", ":model", "gemini:", "other:model", "gemini:a b"])
def test_invalid_model_route(route: str) -> None:
    with pytest.raises(ValidationError, match="provider:model"):
        Settings(_env_file=None, llm_analyzer=route)


def test_fake_script_record_replay_and_exhaustion(tmp_path: Path) -> None:
    outputs = [LLMResponse('{"intent":"checkin"}', 12, 5), LLMResponse("Saved", 8, 1)]
    fake = FakeLLMClient(outputs)
    client: LLMClient = fake
    messages = [LLMMessage("user", "Synthetic note")]
    for expected in outputs:
        assert client.generate(messages, max_tokens=80, temperature=0, ctx=context()) == expected
    assert len(fake.calls) == 2
    recording = tmp_path / "recording.json"
    fake.save(recording)
    replay = FakeLLMClient.from_recording(recording)
    for expected in outputs:
        assert replay.generate(messages, max_tokens=80, temperature=0, ctx=context()) == expected
    with pytest.raises(RuntimeError, match="exhausted"):
        replay.generate(messages, max_tokens=80, temperature=0, ctx=context())
    with pytest.raises(RuntimeError, match="exhausted"):
        fake.generate(messages, max_tokens=80, temperature=0, ctx=context())
    unmatched = FakeLLMClient.from_recording(recording)
    with pytest.raises(RuntimeError, match="exhausted"):
        unmatched.generate(messages, max_tokens=80, temperature=0, ctx=context("composer"))


def test_fake_refuses_recording_real_data(tmp_path: Path) -> None:
    fake = FakeLLMClient([LLMResponse("Saved")])
    ctx = CallContext("analyzer", "real", UUID(int=2), UUID(int=3))
    fake.generate([LLMMessage("user", "note")], max_tokens=80, temperature=0, ctx=ctx)
    with pytest.raises(ValueError, match="synthetic"):
        fake.save(tmp_path / "real.json")


def test_outbound_network_is_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.socket()


@pytest.mark.parametrize(
    ("phase", "expected"),
    [(0, "(p0) and not live"), (3, "(p0 or p1 or p2 or p3) and not live")],
)
def test_cumulative_gate_expression(phase: int, expected: str) -> None:
    assert marker_expression(phase) == expected
    assert frontend_expression(phase) == rf"\[p[0-{phase}]\]"


@pytest.mark.parametrize("phase", [-1, 10])
def test_gate_rejects_invalid_phase(phase: int) -> None:
    with pytest.raises(ValueError, match="0.*9"):
        marker_expression(phase)


def test_stats_import_boundary() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "stats"
    allowed = {"numpy", "scipy", "pandas", "app", "stats"}
    import sys

    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] in allowed | sys.stdlib_module_names, (path, name)
                assert not name.startswith("app.") or name.startswith("app.stats"), (path, name)
                assert name not in {"socket", "urllib", "http", "ftplib"}, (path, name)

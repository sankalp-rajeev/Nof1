"""Readiness contracts are offline; persona validation remains strict."""

import subprocess
from uuid import UUID

import pytest

from app.agent.llm.base import CallContext, LLMResponse, ProviderError
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.tracing import MemoryTraceStore
from app.config import Settings
from sim.extraction import Label
from sim.gpu_preflight import _read, require_free_vram, require_full_gpu
from sim.ollama_recovery import warmup_persona
from sim.personas import persona_card
from sim.render import render

pytestmark = pytest.mark.p8
CTX = CallContext("persona", "synthetic", None, UUID(int=901))
HEADER = "NAME    ID    SIZE    PROCESSOR    CONTEXT    UNTIL\n"


@pytest.mark.parametrize("free,allowed", [(10240, True), (11000, True), (10239, False)])
def test_vram_requires_ten_gib_before_loading(
    free: int, allowed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sim.gpu_preflight._read", lambda _: str(free))
    if allowed:
        assert require_free_vram() == free
    else:
        with pytest.raises(ProviderError, match="10240 MiB"):
            require_free_vram()


@pytest.mark.parametrize("output", ["N/A", "", "11000\n11000"])
def test_unknown_or_ambiguous_vram_fails_closed(
    output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sim.gpu_preflight._read", lambda _: output)
    with pytest.raises(ProviderError, match="gpu_preflight_unavailable"):
        require_free_vram()


@pytest.mark.parametrize("processor", ["100% GPU", "86%/14% CPU/GPU", "100% CPU"])
def test_exact_persona_requires_full_gpu(processor: str, monkeypatch: pytest.MonkeyPatch) -> None:
    output = HEADER + f"gemma3:12b    fixture    9.9 GB    {processor}    4096    24h\n"
    monkeypatch.setattr("sim.gpu_preflight._read", lambda _: output)
    if processor == "100% GPU":
        require_full_gpu("gemma3:12b")
    else:
        with pytest.raises(ProviderError, match="require 100% GPU"):
            require_full_gpu("gemma3:12b")


@pytest.mark.parametrize("output", ["", HEADER, "bad output"])
def test_missing_persona_or_unreadable_placement_refuses(
    output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sim.gpu_preflight._read", lambda _: output)
    with pytest.raises(ProviderError):
        require_full_gpu("gemma3:12b")


def test_probe_failure_is_clear_and_never_exposes_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        assert kwargs["timeout"] == 5
        assert kwargs["capture_output"] is True
        raise subprocess.CalledProcessError(1, ["ollama", "ps"], stderr="private diagnostic")

    monkeypatch.setattr("sim.gpu_preflight.subprocess.run", failed)
    with pytest.raises(ProviderError, match="ollama check failed") as error:
        _read(["ollama", "ps"])
    assert "private diagnostic" not in str(error.value)


def fake_router(outputs: list[LLMResponse]) -> tuple[LLMRouter, FakeLLMClient, MemoryTraceStore]:
    fake = FakeLLMClient(outputs)
    store = MemoryTraceStore()
    router = LLMRouter(
        Settings(_env_file=None, sim_persona="ollama:gemma3:12b"),
        store=store,
        prices=PriceBook({}),
        clients={"ollama": fake},
    )
    return router, fake, store


@pytest.mark.parametrize("reply", ["{}", "invalid json", ""])
def test_warmup_checks_arrival_and_gpu_only(reply: str, monkeypatch: pytest.MonkeyPatch) -> None:
    router, fake, store = fake_router([LLMResponse(reply, 275, 2)])
    checked: list[str] = []
    monkeypatch.setattr("sim.ollama_recovery.require_full_gpu", checked.append)
    warmup_persona(router, CTX)
    assert checked == ["gemma3:12b"] and len(fake.calls) == 1
    assert store.rows[0].status == "ok"


def test_warmup_refuses_cpu_offload_after_response(monkeypatch: pytest.MonkeyPatch) -> None:
    router, fake, store = fake_router([LLMResponse("{}", 275, 2)])
    monkeypatch.setattr(
        "sim.gpu_preflight._read",
        lambda _: HEADER + "gemma3:12b    fixture    9.9 GB    100% CPU    4096    24h\n",
    )
    with pytest.raises(ProviderError, match="require 100% GPU"):
        warmup_persona(router, CTX)
    assert len(fake.calls) == 1 and store.rows[0].status == "ok"


def test_persona_empty_object_still_uses_full_schema_and_existing_fallback() -> None:
    router, fake, store = fake_router([LLMResponse("{}", 275, 2)] * 3)
    result = render(router, (Label(kind="med", name="magnesium"),), persona_card(0), ctx=CTX)
    assert result.fallback and result.attempts == len(fake.calls) == 3
    assert all(row.status == "invalid" and row.error == "render:schema" for row in store.rows)

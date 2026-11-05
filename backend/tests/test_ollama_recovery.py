"""Persona restart recovery and warm-up, using only scripted/mocked transports."""

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agent.llm.base import CallContext, LLMMessage, LLMResponse, ProviderError
from app.agent.llm.cost import BudgetExceeded, Price, PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.openai_compat import OpenAICompatClient
from app.agent.tracing import MemoryTraceStore, SQLTraceStore
from app.config import Settings
from app.db import models as m
from sim.chat_runner import run_chat
from sim.config import E4_OLLAMA_BASE_URL, E4_PERSONA_KEEP_ALIVE, E4_PERSONA_TIMEOUT_S
from sim.live_limits import LimitedRouter, LiveLimits
from sim.ollama_recovery import PersonaRecovery, ollama_ready
from sim.render import RenderedText
from tests.test_chat_sim_runner import configured
from tests.test_storage import engine

pytestmark = pytest.mark.p8
__all__ = ["engine"]
ROUTE = "ollama:gemma3:12b"
CTX = CallContext("persona", "synthetic", None, UUID(int=81))


@pytest.fixture(autouse=True)
def offline_gpu_placement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Warm-up uses a fake placement check; no command or server runs in tests."""
    monkeypatch.setattr("sim.ollama_recovery.require_full_gpu", lambda _: None)


class RestartFake(FakeLLMClient):
    def __init__(self, errors: int) -> None:
        super().__init__([LLMResponse('{"text":"Ready."}', 10, 5)] * 10)
        self.errors = errors

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        result = super().generate(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
        )
        if len(self.calls) <= self.errors:
            raise ProviderError("provider_status", status_code=503)
        return result


def recovering(
    tmp_path: Path, errors: int, ready: Sequence[bool], max_calls: int = 5000
) -> tuple[LimitedRouter, RestartFake, MemoryTraceStore, list[float]]:
    fake = RestartFake(errors)
    prices = PriceBook({ROUTE: Price(Decimal(0), Decimal(0))})
    store = MemoryTraceStore()
    waits: list[float] = []
    router = LimitedRouter(
        Settings(_env_file=None, sim_persona=ROUTE),
        store=store,
        prices=prices,
        clients={ROUTE: fake},
        sleep=waits.append,
    )
    router.tape = []
    router.limits = LiveLimits(prices, tmp_path / "ledger.json", max_calls=max_calls)
    readiness = iter(ready)
    router.persona_recovery = PersonaRecovery(lambda: next(readiness))
    return router, fake, store, waits


def test_waits_for_restart_and_checks_readiness_before_retry(tmp_path: Path) -> None:
    router, fake, store, waits = recovering(tmp_path, 1, [False, True])
    response = router.get("persona").generate([], max_tokens=800, temperature=0, ctx=CTX)
    assert response.text == '{"text":"Ready."}'
    assert waits == [45, 45]
    assert len(fake.calls) == len(store.rows) == router.limits.summary()["actual_calls"] == 2
    assert [row.status for row in store.rows] == ["error", "ok"]
    assert router.persona_recovery.readiness_checks == 2
    assert router.persona_recovery.retry_dispatches == 1


def test_four_retries_have_no_nested_http_retries_and_stop_cleanly(tmp_path: Path) -> None:
    router, fake, store, waits = recovering(tmp_path, 10, [True] * 4)
    with pytest.raises(ProviderError, match="persona_retries_exhausted"):
        router.get("persona").generate([], max_tokens=800, temperature=0, ctx=CTX)
    assert waits == [45] * 4 and sum(waits) == 180
    assert len(fake.calls) == len(store.rows) == router.limits.summary()["actual_calls"] == 5
    assert router.persona_recovery.exhausted
    assert router.persona_recovery.last_error == "provider_status"
    assert all(row.status == "error" for row in store.rows)


def test_server_down_does_not_dispatch_retries(tmp_path: Path) -> None:
    router, fake, store, waits = recovering(tmp_path, 10, [False] * 4)
    with pytest.raises(ProviderError, match="persona_retries_exhausted"):
        router.get("persona").generate([], max_tokens=800, temperature=0, ctx=CTX)
    assert len(fake.calls) == len(store.rows) == 1
    assert router.persona_recovery.retry_dispatches == 0
    assert sum(waits) == 180


def test_call_cap_remains_authoritative_during_recovery(tmp_path: Path) -> None:
    router, fake, store, waits = recovering(tmp_path, 10, [True] * 4, max_calls=2)
    with pytest.raises(BudgetExceeded):
        router.get("persona").generate([], max_tokens=800, temperature=0, ctx=CTX)
    assert len(fake.calls) == router.limits.summary()["actual_calls"] == 2
    assert router.limits.summary()["stop_reason"] == "call_cap"


@pytest.mark.parametrize("healthy", [False, True])
def test_inventory_probe_is_read_only(monkeypatch: pytest.MonkeyPatch, healthy: bool) -> None:
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/v1/models"
        return httpx.Response(200 if healthy else 503, json={"data": []})

    original = httpx.Client
    monkeypatch.setattr(
        "sim.ollama_recovery.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(answer), **kwargs),
    )
    assert ollama_ready(E4_OLLAMA_BASE_URL) is healthy
    assert len(requests) == 1


def test_eval_ollama_request_keeps_model_loaded_without_changing_prompt(tmp_path: Path) -> None:
    payloads: list[dict[str, object]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "Ready."},
                "done": True,
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(answer)) as http:
        sdk = OpenAI(api_key="ollama", base_url=E4_OLLAMA_BASE_URL, max_retries=0, http_client=http)
        router, _, _, _ = recovering(tmp_path, 0, [])
        router.clients = {ROUTE: OpenAICompatClient(sdk, "gemma3:12b")}
        router.persona_timeout_s = E4_PERSONA_TIMEOUT_S
        messages = [LLMMessage("user", "Frozen synthetic content")]
        router.get("persona").generate(
            messages, schema=RenderedText, max_tokens=800, temperature=0, ctx=CTX
        )
    assert payloads[0]["keep_alive"] == E4_PERSONA_KEEP_ALIVE == "24h"
    assert payloads[0]["messages"] == [{"role": "user", "content": "Frozen synthetic content"}]
    assert payloads[0]["options"] == {"num_predict": 800, "temperature": 0, "top_p": 1.0}
    assert payloads[0]["stream"] is False
    assert payloads[0]["format"] == "json"


def test_warmup_precedes_cohort_is_traced_and_excluded_from_e4(engine: Engine) -> None:
    settings, router, fake = configured(engine)
    report, bundle = run_chat(
        settings,
        engine,
        seeds=[0],
        days=1,
        router=router,
        include_e7=False,
        warmup_persona_enabled=True,
    )
    assert report["persona_warmup_completed"] is True
    assert fake.calls[0].ctx.purpose == "persona"
    assert json.loads(fake.calls[0].messages[1].content)["events"] == []
    assert all(case.id != "persona_warmup" for case in bundle.cases)
    assert report["completed_patients"] == 1
    assert report["total_traced_attempts"] == len(fake.calls)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(m.User)) == 0
        assert session.scalar(select(func.count()).select_from(m.LLMCall)) == 0


def test_warmup_discards_unused_reply_without_schema_validation(engine: Engine) -> None:
    settings, router, _ = configured(engine)
    fake = FakeLLMClient([LLMResponse("invalid json", 10, 5)])
    router.clients = {"ollama": fake}
    report, bundle = run_chat(
        settings,
        engine,
        seeds=[],
        days=1,
        router=router,
        include_e7=False,
        warmup_persona_enabled=True,
    )
    assert report["stopped"] is None
    assert report["persona_warmup_completed"] is True
    assert not report["failure_case_ids"].get("invalid", [])
    assert report["completed_patients"] == 0 and not bundle.cases
    assert len(fake.calls) == 1


def test_exhausted_warmup_reports_reason_and_metered_attempts_then_cleans_up(
    engine: Engine, tmp_path: Path
) -> None:
    router, fake, _, waits = recovering(tmp_path, 10, [True] * 4)
    router.store = SQLTraceStore(engine)
    router.cost.store = router.store
    report, bundle = run_chat(
        router.settings,
        engine,
        seeds=[0],
        days=1,
        router=router,
        include_e7=False,
        limits=router.limits,
        warmup_persona_enabled=True,
    )
    assert report["stopped"] == "provider_failure"
    assert report["provider_failure_reason"] == "persona_retries_exhausted"
    assert report["failure_case_ids"]["provider_error"] == ["persona_warmup"]
    assert report["completed_patients"] == report["turns"] == 0
    assert report["total_traced_attempts"] == router.limits.summary()["actual_calls"] == 5
    assert report["E8"]["latency_ms"] == {}
    assert len(fake.calls) == 5 and sum(waits) == 180 and not bundle.cases
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(m.User)) == 0
        assert session.scalar(select(func.count()).select_from(m.LLMCall)) == 0

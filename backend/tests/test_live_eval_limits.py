"""Offline enforcement tests for the single authorized P8 live evaluation."""

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine

from app.agent.evaluation import adversarial_cases
from app.agent.llm.base import CallContext, LLMMessage, LLMResponse, ProviderError
from app.agent.llm.cost import BudgetExceeded, Price, PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.tracing import MemoryTraceStore
from app.config import Settings
from sim.chat_runner import run_chat
from sim.live_limits import LimitedClient, LimitedRouter, LiveLimits, claim_run
from tests.test_chat_sim_runner import configured
from tests.test_storage import engine

pytestmark = pytest.mark.p8
__all__ = ["engine"]
CTX = CallContext("analyzer", "synthetic", None, UUID(int=1))
ROUTE = "gemini:gemini-3.1-flash-lite"


class ErrorFake(FakeLLMClient):
    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        self._outputs.append(LLMResponse(""))
        super().generate(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
        )
        raise ProviderError("unavailable", status_code=503)


def prices() -> PriceBook:
    return PriceBook(
        {
            ROUTE: Price(Decimal("0.25"), Decimal("1.50")),
            "ollama:gemma3:12b": Price(Decimal(0), Decimal(0)),
        }
    )


def test_global_call_cap_counts_concurrent_zero_cost_dispatches(tmp_path: Path) -> None:
    limits = LiveLimits(prices(), tmp_path / "ledger.json", max_calls=3)
    fake = FakeLLMClient([LLMResponse("private health text", 10, 5)] * 10)
    client = LimitedClient(fake, limits, "ollama:gemma3:12b")

    def call(_: int) -> None:
        try:
            client.generate([], max_tokens=800, temperature=0, ctx=CTX)
        except BudgetExceeded:
            pass

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(call, range(10)))
    assert len(fake.calls) == limits.summary()["actual_calls"] == 3
    assert limits.summary()["actual_cost_usd"] == "0"
    assert "private health text" not in (tmp_path / "ledger.json").read_text()


def test_reserves_documented_input_bound_and_settles_exact_usage(tmp_path: Path) -> None:
    limits = LiveLimits(prices(), tmp_path / "ledger.json", cap=Decimal("0.30"))
    index, reserve = limits.reserve(ROUTE, 800, CTX)
    assert reserve == Decimal("0.263344")
    with pytest.raises(BudgetExceeded):
        limits.reserve(ROUTE, 800, CTX)
    limits.settle(index, reserve, LLMResponse("ignored", 100, 20))
    assert limits.summary()["actual_cost_usd"] == "0.000055"
    assert limits.summary()["actual_calls"] == 1
    assert limits.summary()["accounted_upper_bound_usd"] == "0.000055"
    # A refusal latches: later dates/users/settlement cannot restart a stopped run.
    with pytest.raises(BudgetExceeded):
        limits.reserve(ROUTE, 800, CTX)


def test_missing_prices_and_unknown_models_fail_closed(tmp_path: Path) -> None:
    for number, route in enumerate(["gemini:unknown", "deepseek:unknown"]):
        limits = LiveLimits(prices(), tmp_path / f"{number}.json")
        with pytest.raises(BudgetExceeded):
            limits.reserve(route, 800, CTX)
        assert limits.summary()["actual_calls"] == 0


def test_paid_errors_keep_full_reservation_and_do_not_invent_zero_cost(tmp_path: Path) -> None:
    limits = LiveLimits(prices(), tmp_path / "ledger.json")
    fake = ErrorFake()
    client = LimitedClient(fake, limits, ROUTE)
    with pytest.raises(ProviderError):
        client.generate([], max_tokens=800, temperature=0, ctx=CTX)
    assert limits.summary()["actual_cost_usd"] is None
    assert limits.summary()["unsettled_upper_bound_usd"] == "0.263344"
    assert limits.summary()["actual_calls"] == 1


def test_missing_paid_usage_never_releases_the_reservation(tmp_path: Path) -> None:
    limits = LiveLimits(prices(), tmp_path / "ledger.json")
    index, reserve = limits.reserve(ROUTE, 800, CTX)
    limits.settle(index, reserve, LLMResponse("generated without output usage", 10, 0))
    assert limits.summary()["actual_cost_usd"] is None
    assert limits.summary()["accounted_upper_bound_usd"] == "0.263344"


def test_router_transport_retries_each_pass_the_dispatch_cap(tmp_path: Path) -> None:
    limits = LiveLimits(prices(), tmp_path / "ledger.json", max_calls=2)
    fake = ErrorFake()
    settings = Settings(_env_file=None, llm_analyzer=ROUTE)
    router = LimitedRouter(
        settings,
        store=MemoryTraceStore(),
        prices=prices(),
        clients={"gemini": fake},
        sleep=lambda _: None,
    )
    router.tape, router.limits = [], limits
    with pytest.raises(BudgetExceeded):
        router.get("analyzer").generate([], max_tokens=800, temperature=0, ctx=CTX)
    assert len(fake.calls) == limits.summary()["actual_calls"] == 2
    assert limits.summary()["accounted_upper_bound_usd"] == "0.526688"


def test_once_claim_is_exclusive_even_after_interruption(tmp_path: Path) -> None:
    path = tmp_path / "once"
    claim_run(path)
    with pytest.raises(FileExistsError):
        claim_run(path)
    assert json.loads((path / "STARTED.json").read_text())["rerun_allowed"] is False


def test_safety_precedes_persona_and_cohort_attempts(engine: Engine) -> None:
    settings, router, fake = configured(engine)
    report, _ = run_chat(settings, engine, seeds=[0], days=1, router=router)
    first_persona = next(i for i, call in enumerate(fake.calls) if call.ctx.purpose == "persona")
    safety_users = {call.ctx.user_id for call in fake.calls[:first_persona]}
    cohort_users = {call.ctx.user_id for call in fake.calls[first_persona:]}
    assert safety_users and safety_users.isdisjoint(cohort_users)
    assert report["E7"]["tested"] == len(adversarial_cases())
    assert report["ordering"] == "safety_first"
    assert all(isinstance(ids, list) for ids in report["failure_case_ids"].values())


def test_safety_budget_stop_prevents_cohort(engine: Engine) -> None:
    settings, router, fake = configured(engine, tokens=1)
    report, _ = run_chat(settings, engine, seeds=[0], days=1, router=router)
    assert report["stopped"] == "budget_exhausted_during_e7"
    assert report["renders"] == 0 and not fake.calls
    assert report["failure_case_ids"]["incomplete"]

"""Synthetic agent integration with a scripted FakeLLM; no live eval is performed."""

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.agent.evaluation import adversarial_cases
from app.agent.llm.base import CallContext, LLMMessage, LLMResponse
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.tracing import CallTrace, SQLTraceStore
from app.config import Settings
from app.db import models as m
from sim.chat_runner import latency_report, run_chat
from sim.config import EXPOSURES
from sim.extraction import Label
from sim.render import template
from sim.replay import RecordingRouter, replay_bundle
from tests.test_storage import engine

pytestmark = pytest.mark.p8
__all__ = ["engine"]


class ObservationFake(FakeLLMClient):
    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        payload = json.loads(
            next(message.content for message in reversed(messages) if message.role == "user")
        )
        if ctx.purpose == "persona":
            text = template(tuple(Label.model_validate(e) for e in payload["events"]))
            output = {"text": text}
        elif ctx.purpose == "analyzer":
            text = payload["user_text"].casefold()
            events = []
            for clause in text.split(";"):
                for name in EXPOSURES:
                    if name in clause:
                        events.append(
                            {
                                "kind": "med"
                                if name in {"magnesium", "electrolytes"}
                                else "life"
                                if name == "walk"
                                else "meal",
                                "name": name,
                                "status": "skipped" if "skipped" in clause else "done",
                            }
                        )
                match = re.search(r"fatigue (\d+)", clause)
                if match:
                    events.append({"kind": "symptom", "name": "fatigue", "severity": int(match[1])})
                match = re.search(r"sleep (\d+(?:\.\d+)?)", clause)
                if match:
                    events.append(
                        {"kind": "sleep", "name": "sleep", "value": float(match[1]), "unit": "h"}
                    )
            output = {
                "intent": "checkin",
                "events": events,
                "ratings": [
                    {"outcome": "fatigue", "value": e["severity"]}
                    for e in events
                    if e["kind"] == "symptom"
                ],
            }
        else:
            output = {"reply": "Thanks for the update."}
        self._outputs.append(LLMResponse(json.dumps(output), 10, 5))
        return super().generate(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
        )


def configured(
    engine: Engine, tokens: int = 60000
) -> tuple[Settings, RecordingRouter, ObservationFake]:
    settings = Settings(
        _env_file=None,
        sim_persona="ollama:persona-fixture",
        llm_analyzer="ollama:extractor-fixture",
        llm_composer="ollama:composer-fixture",
        llm_narrator="ollama:narrator-fixture",
        max_total_tokens=tokens,
    )
    fake = ObservationFake()
    router = RecordingRouter(
        settings,
        store=SQLTraceStore(engine),
        prices=PriceBook({}),
        clients={"ollama": fake},
        sleep=lambda _: None,
    )
    router.tape = []
    return settings, router, fake


def test_chat_cohort_runs_through_agent_and_replays_with_only_synthetic_calls(
    engine: Engine,
) -> None:
    settings, router, fake = configured(engine)
    report, bundle = run_chat(settings, engine, seeds=[0], days=1, router=router, include_e7=False)
    assert report["completed_patients"] == 1 and report["stopped"] is None
    assert report["turns"] >= 1
    assert report["E4"]["f1"] == 1.0
    assert replay_bundle(bundle) == bundle.expected
    assert fake.calls and all(call.ctx.data_class == "synthetic" for call in fake.calls)
    for call in fake.calls:
        if call.ctx.purpose == "persona":
            assert set(json.loads(call.messages[1].content)) == {"events", "persona"}
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(m.User)) == 0
        assert session.scalar(select(func.count()).select_from(m.LLMCall)) == 0


def test_budget_stop_is_partial_not_a_silent_template_only_live_success(engine: Engine) -> None:
    settings, router, fake = configured(engine, tokens=1)
    report, bundle = run_chat(settings, engine, seeds=[0], days=1, router=router, include_e7=False)
    assert report["stopped"] == "budget_exhausted"
    assert report["completed_patients"] == 0 and report["E4"] is None
    assert not fake.calls and not bundle.cases
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(m.User)) == 0


def test_e7_driver_uses_isolated_synthetic_users_and_reports_every_case(engine: Engine) -> None:
    settings, router, fake = configured(engine)
    report, _ = run_chat(settings, engine, seeds=[0], days=1, router=router)
    assert report["E7"] == {"tested": len(adversarial_cases()), "failed": [], "pending": False}
    assert all(call.ctx.data_class == "synthetic" for call in fake.calls)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(m.User)) == 0


def test_trace_metrics_measure_quantiles_and_preserve_unknown_cost() -> None:
    first = CallTrace(
        id=UUID(int=1),
        trace_id=UUID(int=2),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        purpose="analyzer",
        provider="ollama",
        model="fixture",
        prompt_version=1,
        data_class="synthetic",
        attempt=1,
        input_tokens=10,
        output_tokens=5,
        latency_ms=10,
        cost_usd=None,
        status="ok",
    )
    second = first.model_copy(update={"latency_ms": 30})
    report = latency_report([first, second], turns=2, regenerated=1, fallback=0, all_fallbacks=1)
    assert report["latency_ms"]["analyzer"] == {"mean": 20.0, "p95": 29.0, "calls": 2}
    assert report["guard_regen_rate"] == 0.5 and report["all_fallback_rate"] == 0.5
    assert report["guard_fallback_rate"] == 0
    assert report["cost_per_100_turns_usd"] is None
    assert report["input_tokens"] == 20 and report["output_tokens"] == 10


def test_prior_patient_ledgers_survive_until_the_last_evaluation_call(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, router, fake = configured(engine)
    original = fake.generate
    seen: set[UUID] = set()
    checked: list[bool] = []

    def inspect(
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        assert ctx.user_id is not None
        if seen and ctx.user_id not in seen:
            with Session(engine) as session:
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(m.LLMCall)
                        .where(m.LLMCall.user_id.in_(seen))
                    )
                    > 0
                )
                checked.append(True)
        seen.add(ctx.user_id)
        return original(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
        )

    monkeypatch.setattr(fake, "generate", inspect)
    report, _ = run_chat(settings, engine, seeds=[0, 1], days=1, router=router, include_e7=False)
    assert report["stopped"] is None and checked
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(m.User)) == 0
        assert session.scalar(select(func.count()).select_from(m.LLMCall)) == 0

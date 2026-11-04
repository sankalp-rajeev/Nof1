"""Bounded synthetic cohort driver. Truth stays in code; the real agent sees text only."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time
from uuid import UUID, uuid4

import numpy as np
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.agent.evaluation import adversarial_cases
from app.agent.experiment_manager import PROTOCOL, ExperimentManager
from app.agent.llm.base import CallContext, ProviderError
from app.agent.llm.cost import BudgetExceeded, PriceBook
from app.agent.orchestrator import ChatResult, Orchestrator
from app.agent.safety.output_guard import Facts, OutputGuard
from app.agent.tracing import CallTrace, SQLTraceStore
from app.config import Settings
from app.db import models as m
from app.db.repos import Repository
from app.domain.schemas import ExposureChecklist, Pending, UserInput
from sim.config import ADHERENCE_P, CHAT_DAYS, COHORT_L, EXPOSURES, MAX_FOLLOWUPS, OUTCOME
from sim.extraction import ExtractionScore, Label
from sim.personas import mention_plan, observed_events, participation, persona_card, persona_reply
from sim.render import render
from sim.replay import RecordingRouter, ReplayBundle, ReplayCase, replay_case, score_dict
from sim.world import generate_world, simulate_experiment

JSON = TypeAdapter(dict[str, JsonValue])


@dataclass
class LogicalClock:
    instant: datetime

    def __call__(self) -> datetime:
        return self.instant


def latency_report(
    calls: Sequence[CallTrace], *, turns: int, regenerated: int, fallback: int, all_fallbacks: int
) -> dict[str, JsonValue]:
    groups: dict[str, list[float]] = defaultdict(list)
    for call in calls:
        groups[call.purpose].append(call.latency_ms)
    total_cost = (
        sum(c.cost_usd or 0 for c in calls) if all(c.cost_usd is not None for c in calls) else None
    )
    return JSON.validate_python(
        {
            "guard_regen_rate": regenerated / turns if turns else None,
            "guard_fallback_rate": fallback / turns if turns else None,
            "all_fallback_rate": all_fallbacks / turns if turns else None,
            "latency_ms": {
                purpose: {
                    "mean": float(np.mean(values)),
                    "p95": float(np.percentile(values, 95)),
                    "calls": len(values),
                }
                for purpose, values in groups.items()
            },
            "cost_per_100_turns_usd": total_cost * 100 / turns
            if total_cost is not None and turns
            else None,
            "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls),
            "unknown_price_calls": sum(c.cost_usd is None for c in calls),
            "provider_error_calls": sum(c.status == "error" for c in calls),
            "invalid_calls": sum(c.status == "invalid" for c in calls),
        }
    )


def make_case(
    router: RecordingRouter,
    result: ChatResult,
    text: str,
    gold: tuple[Label, ...],
    pending: Pending | None,
    identity: str,
) -> ReplayCase:
    attempts = tuple(
        row
        for row in router.tape
        if row.ctx.trace_id == result.trace_id and row.ctx.purpose == "analyzer"
    )
    case = ReplayCase(
        id=identity,
        gold=gold,
        text=text,
        pending=pending,
        attempts=attempts,
        expected=ExtractionScore(),
    )
    return case.model_copy(
        update={"expected": replay_case(case, router.settings.max_output_tokens)}
    )


def run_chat(
    settings: Settings,
    engine: Engine,
    *,
    seeds: Sequence[int] = COHORT_L,
    days: int = CHAT_DAYS,
    router: RecordingRouter | None = None,
    include_e7: bool = True,
) -> tuple[dict[str, JsonValue], ReplayBundle]:
    created_users: list[UUID] = []
    try:
        return _run_chat(
            settings,
            engine,
            seeds=seeds,
            days=days,
            router=router,
            include_e7=include_e7,
            created_users=created_users,
        )
    finally:
        # Preserve all trace rows until the last call: CLI budget reservations
        # query them by ID, and user deletion cascades into the call ledger.
        with Session(engine) as session, session.begin():
            repo = Repository(session)
            for uid in created_users:
                if repo.get_user(uid) is not None:
                    repo.delete_user(uid)


def _run_chat(
    settings: Settings,
    engine: Engine,
    *,
    seeds: Sequence[int],
    days: int,
    router: RecordingRouter | None,
    include_e7: bool,
    created_users: list[UUID],
) -> tuple[dict[str, JsonValue], ReplayBundle]:
    if days < 1 or days > CHAT_DAYS:
        raise ValueError("Chat evaluation supports 1..30 days")
    clock = LogicalClock(datetime(2026, 1, 1, 12, tzinfo=UTC))
    if router is None:
        router = RecordingRouter(
            settings, store=SQLTraceStore(engine), prices=PriceBook.load(), clock=clock, mode="cli"
        )
        router.tape = []
    else:
        router.clock = clock
        router.cost.clock = clock
    agent = Orchestrator(engine, router, clock=clock)
    cases: list[ReplayCase] = []
    calls: list[CallTrace] = []
    turns = regenerated = fallback = all_fallbacks = 0
    renders = render_fallbacks = dropped = bounded = 0
    completed = 0
    stopped: str | None = None

    def new_user() -> UUID:
        with Session(engine) as session, session.begin():
            repo = Repository(session)
            uid = repo.create_user(UserInput(data_class="synthetic", tz="UTC")).id
            created_users.append(uid)
            repo.set_tracking(
                uid, outcomes=[(OUTCOME, "lower")], exposures=list(EXPOSURES[:5]), track_sleep=True
            )
            return uid

    def capture_calls(uid: UUID) -> None:
        with Session(engine) as session, session.begin():
            calls.extend(
                CallTrace.model_validate(row)
                for row in session.scalars(select(m.LLMCall).where(m.LLMCall.user_id == uid))
            )

    def send(uid: UUID, text: str, labels: tuple[Label, ...], identity: str) -> ChatResult:
        nonlocal turns, regenerated, fallback, all_fallbacks
        with Session(engine) as session:
            pending = Repository(session).get_state(uid).pending
        result = agent.process(uid, text, client_msg_id=uuid4())
        turns += 1
        regenerated += int(result.regenerated)
        fallback += int(result.regenerated and result.fallback)
        all_fallbacks += int(result.fallback)
        cases.append(make_case(router, result, text, labels, pending, identity))
        if result.limited:
            raise BudgetExceeded("App entered limited mode")
        return result

    try:
        for seed in seeds:
            world = generate_world(seed, days=days)
            calendar = list(world.days)
            card = persona_card(seed)
            uid = new_user()
            simulated: set[UUID] = set()
            compliance: dict[str, bool | None] = {}
            try:
                for index, initial_day in enumerate(calendar):
                    drop, _ = participation(seed, index)
                    if drop:
                        dropped += 1
                        break
                    clock.instant = datetime.combine(initial_day.date, time(12), UTC)
                    # Apply an accepted protocol using the same world's continuation.
                    with Session(engine) as session:
                        active = ExperimentManager(Repository(session), uid, clock=clock).active()
                        if (
                            active is not None
                            and active.started_on == initial_day.date
                            and active.id not in simulated
                        ):
                            protocol = PROTOCOL.validate_python(active.protocol)
                            continuation = simulate_experiment(
                                generate_world(seed, days=index), protocol, ADHERENCE_P
                            )
                            simulated.add(active.id)
                            for offset, day in enumerate(continuation.days):
                                if index + offset < len(calendar):
                                    calendar[index + offset] = day
                            compliance.update(
                                {
                                    row.date.isoformat(): row.adherence
                                    for row in continuation.observations
                                }
                            )
                    day = calendar[index]
                    if not day.observed:
                        continue
                    events = observed_events(day)
                    style = (
                        card.model_copy(update={"verbosity": "terse"})
                        if card.fatigue_sensitivity and day.y >= 7
                        else card
                    )
                    plan = mention_plan(events, card, seed=seed * CHAT_DAYS + index)
                    result = render(
                        router, plan, style, ctx=CallContext("persona", "synthetic", uid, uuid4())
                    )
                    renders += 1
                    render_fallbacks += int(result.fallback)
                    send(uid, result.text, plan, f"{seed}:{index}:free")
                    for follow_index in range(MAX_FOLLOWUPS):
                        with Session(engine) as session:
                            pending = Repository(session).get_state(uid).pending
                        if pending is None:
                            break
                        answer = persona_reply(
                            pending,
                            observed_events(day, checklist=True)
                            if isinstance(pending, ExposureChecklist)
                            else events,
                            seed=seed * 1000 + index * MAX_FOLLOWUPS + follow_index,
                            adherence=compliance.get(day.date.isoformat()),
                        )
                        if answer.fixed is not None:
                            text = answer.fixed
                        else:
                            phrased = render(
                                router,
                                answer.events,
                                style,
                                ctx=CallContext("persona", "synthetic", uid, uuid4()),
                            )
                            renders += 1
                            render_fallbacks += int(phrased.fallback)
                            text = phrased.text
                        send(uid, text, answer.events, f"{seed}:{index}:{follow_index}")
                    else:
                        bounded += 1
                completed += 1
            finally:
                capture_calls(uid)
    except BudgetExceeded:
        stopped = "budget_exhausted"
    except ProviderError:
        stopped = "provider_failure"

    e8 = latency_report(
        calls, turns=turns, regenerated=regenerated, fallback=fallback, all_fallbacks=all_fallbacks
    )
    e7_failed: list[str] = []
    e7_tested = 0
    if include_e7 and stopped is None:
        for item in adversarial_cases():
            uid = new_user()
            try:
                safety_result = agent.process(uid, item.user_text, client_msg_id=uuid4())
                if safety_result.limited:
                    stopped = "budget_exhausted_during_e7"
                    break
                e7_tested += 1
                if {"G1", "G2"} & set(
                    OutputGuard().check(safety_result.reply, safety_result.facts or Facts())
                ):
                    e7_failed.append(item.id)
            finally:
                capture_calls(uid)
    score = ExtractionScore()
    for case in cases:
        score += case.expected
    bundle = ReplayBundle(
        provenance="live_synthetic",
        cases=tuple(cases),
        expected=score,
        max_output_tokens=settings.max_output_tokens,
    )
    report = JSON.validate_python(
        {
            "mode": "live_synthetic",
            "completed_patients": completed,
            "requested_patients": len(seeds),
            "days": days,
            "turns": turns,
            "stopped": stopped,
            "dropouts": dropped,
            "followup_bound_hits": bounded,
            "E4": score_dict(score) if turns else None,
            "E7": {
                "tested": e7_tested,
                "failed": e7_failed,
                "pending": e7_tested < len(adversarial_cases()),
            },
            "E8": e8,
            "renders": renders,
            "render_fallbacks": render_fallbacks,
            "render_fallback_rate": render_fallbacks / renders if renders else None,
            "synthetic_users_deleted": True,
        }
    )
    return report, bundle

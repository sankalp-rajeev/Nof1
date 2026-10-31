"""Transactional chat workflow. Code owns state, ordering, safety, and idempotency."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.agent.analyzer import TurnAnalysis, analyze
from app.agent.composer import (
    CLARIFY,
    FAILED,
    LIMITED,
    PROVIDER_FAILED,
    Composed,
    build_facts,
    compose,
    safe_fixed,
)
from app.agent.context import ContextBuilder
from app.agent.experiment_composer import (
    compose_insight,
    compose_instruction,
    compose_protocol,
    compose_verdict,
    instruction,
)
from app.agent.experiment_manager import ExperimentError, ExperimentManager
from app.agent.insights import InsightSurfacer
from app.agent.llm.base import CallContext, ProviderError
from app.agent.llm.cost import BudgetExceeded
from app.agent.llm.router import LLMRouter
from app.agent.pending import (
    checklist_answer_supported,
    consume,
    next_question,
    question_text,
    record_adherence,
    record_checklist,
    skip_pending,
)
from app.agent.progress import Progress, load_progress, save_progress
from app.agent.receipts import PersistenceReceipts
from app.agent.safety.inbound import inbound_safety
from app.agent.safety.output_guard import Facts
from app.agent.safety.templates import ESCALATION, MEDICAL_REFUSAL
from app.agent.tool_loop import run_readonly_loop
from app.agent.tools.registry import ToolRegistry
from app.config import CHAT_LOCK_NAMESPACE
from app.db import models as m
from app.db.repos import Repository
from app.domain.clock import today
from app.domain.normalize import normalize
from app.domain.schemas import (
    ConfirmExperiment,
    ExperimentAdherence,
    ExposureChecklist,
    MessageInput,
    OnboardingExposures,
    OnboardingOutcomes,
    OnboardingSleep,
    PendingState,
    RateOutcome,
    UserRecord,
)


@dataclass(frozen=True)
class ChatResult:
    reply: str
    trace_id: UUID
    facts: Facts | None = None
    replayed: bool = False
    limited: bool = False
    analyzer_calls: int = 0
    tool_calls: int = 0
    regenerated: bool = False
    fallback: bool = False


class Orchestrator:
    def __init__(
        self,
        engine: Engine,
        router: LLMRouter,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.engine, self.router, self.clock = engine, router, clock

    @staticmethod
    def _lock(session: Session, user_id: UUID) -> None:
        key = int.from_bytes(hashlib.sha256(user_id.bytes).digest()[:4], signed=True)
        session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace,:key)"),
            {"namespace": CHAT_LOCK_NAMESPACE, "key": key},
        )

    def begin(self, user_id: UUID) -> ChatResult:
        with Session(self.engine) as session, session.begin():
            self._lock(session, user_id)
            repo = Repository(session)
            user = repo.get_user(user_id)
            if user is None:
                raise ValueError("User not found")
            manager = ExperimentManager(repo, user_id, clock=self.clock)
            active = manager.advance()
            day = today(user, now=self.clock())
            progress, state = load_progress(repo, user_id, day)
            state.pending = next_question(repo, user_id, day, progress, state)
            save_progress(repo, user_id, progress, state)
            facts = build_facts({"today": day.isoformat()}, state.pending)
            reply = safe_fixed(
                question_text(state.pending) or "Your check-in is up to date.", facts
            )
            if active is not None and active.status in {"baseline", "running"}:
                plan_facts = instruction(active, manager)
                if plan_facts is not None:
                    facts = facts.model_copy(
                        update={
                            "kind": "experiment",
                            "phase": plan_facts.phase,
                            "washout": plan_facts.washout,
                        }
                    )
                    from app.agent.safety.templates import render_fallback

                    reply = safe_fixed(
                        (render_fallback(facts) + " " + question_text(state.pending)).strip(), facts
                    )
            return self._save(repo, user_id, uuid4(), Composed(reply, facts))

    def process(
        self, user_id: UUID, content: str, *, client_msg_id: UUID | None = None
    ) -> ChatResult:
        with Session(self.engine) as session, session.begin():
            self._lock(session, user_id)
            repo = Repository(session)
            user = repo.get_user(user_id)
            if user is None:
                raise ValueError("User not found")
            ExperimentManager(repo, user_id, clock=self.clock).advance()
            if client_msg_id is not None:
                previous = repo.find_message(user_id, client_msg_id)
                if previous is not None:
                    stored_reply = session.scalar(
                        select(m.Message)
                        .where(
                            m.Message.user_id == user_id,
                            m.Message.trace_id == previous.trace_id,
                            m.Message.role == "assistant",
                        )
                        .order_by(m.Message.created_at.desc())
                        .limit(1)
                    )
                    if stored_reply is None:
                        raise RuntimeError("Processed message has no response")
                    return ChatResult(stored_reply.content, stored_reply.trace_id, replayed=True)
            trace_id = uuid4()
            message = repo.add_message(
                user_id,
                MessageInput(
                    role="user", content=content, trace_id=trace_id, client_msg_id=client_msg_id
                ),
            )
            inbound = inbound_safety(content)
            if inbound.red_flag:
                return self._emergency(
                    repo, user_id, message.id, trace_id, inbound.category or "emergency", "rule"
                )
            day = today(user, now=self.clock())
            progress, state = load_progress(repo, user_id, day)
            if state.pending is None and progress.onboarding != "done":
                state.pending = next_question(repo, user_id, day, progress, state)
            tools = ToolRegistry(repo, user_id, day, trace_id, clock=self.clock)
            receipts = PersistenceReceipts(repo, user_id, message.id, day)
            rating_answer = isinstance(state.pending, RateOutcome)
            experiment_answer = isinstance(state.pending, ConfirmExperiment)
            try:
                handled = consume(content, state, progress, tools, message.id)
            except ExperimentError as error:
                state.pending = None
                progress.experiment_confirmation = None
                save_progress(repo, user_id, progress, state)
                return self._save(
                    repo, user_id, trace_id, Composed(str(error), Facts(), fallback=True)
                )
            before_progress, before_state = (
                progress.model_copy(deep=True),
                state.model_copy(deep=True),
            )
            try:
                with session.begin_nested():
                    return self._turn(
                        user,
                        repo,
                        tools,
                        message,
                        content,
                        progress,
                        state,
                        handled,
                        experiment_answer,
                        receipts,
                        rating_answer,
                    )
            except BudgetExceeded:
                progress, state = before_progress, before_state
                ExperimentManager(repo, user_id, clock=self.clock).advance()
                state.pending = next_question(repo, user_id, day, progress, state)
                state.last_was_clarification = False
                save_progress(repo, user_id, progress, state)
                facts = build_facts({"today": day.isoformat()}, state.pending)
                reply = safe_fixed((LIMITED + " " + question_text(state.pending)).strip(), facts)
                return self._save(
                    repo, user_id, trace_id, Composed(reply, facts, fallback=True), limited=True
                )
            except ProviderError:
                progress, state = before_progress, before_state
                reply = PROVIDER_FAILED
                state.last_was_clarification = False
                save_progress(repo, user_id, progress, state)
                return self._save(repo, user_id, trace_id, Composed(reply, Facts(), fallback=True))

    def _turn(
        self,
        user: m.User,
        repo: Repository,
        tools: ToolRegistry,
        message: m.Message,
        content: str,
        progress: Progress,
        state: PendingState,
        handled: bool,
        experiment_answer: bool = False,
        receipts: PersistenceReceipts | None = None,
        rating_answer: bool = False,
    ) -> ChatResult:
        identity = UserRecord.model_validate(user)

        def ctx(purpose: str) -> CallContext:
            return CallContext(purpose, identity.data_class, user.id, message.trace_id)

        builder = ContextBuilder(tools)
        base = builder.base(state, content, message.id)
        calls = 0
        experiment_error: str | None = None
        if handled:
            analysis = TurnAnalysis(intent="experiment" if experiment_answer else "checkin")
        else:
            extracted = analyze(self.router, base.messages, ctx=ctx("analyzer"))
            calls = extracted.attempts
            if extracted.value is None:
                reply = FAILED if state.last_was_clarification else CLARIFY
                state.last_was_clarification = not state.last_was_clarification
                save_progress(repo, user.id, progress, state)
                return self._save(
                    repo,
                    user.id,
                    message.trace_id,
                    Composed(reply, Facts(), fallback=True),
                    calls=calls,
                )
            analysis = extracted.value
            if analysis.possible_emergency:
                return self._emergency(
                    repo, user.id, message.id, message.trace_id, "possible_emergency", "llm", calls
                )
            experiment_error = self._apply(analysis, tools, state, progress, message.id)
        manager = ExperimentManager(repo, user.id, clock=self.clock)
        manager.advance()
        clarification = (
            analysis.clarification_question
            if (
                not state.last_was_clarification
                and analysis.clarification_question
                and (
                    not analysis.events
                    or any(normalize(e.name).category == "unknown" for e in analysis.events)
                )
            )
            else None
        )
        state.last_was_clarification = bool(clarification)
        state.pending = next_question(repo, user.id, tools.day, progress, state)
        save_progress(repo, user.id, progress, state)
        payload: dict[str, JsonValue] = {
            "today": tools.day.isoformat(),
            "intent": analysis.intent,
            "tracking": repo.get_tracking(user.id).model_dump(mode="json"),
            "pending": state.pending.model_dump(mode="json") if state.pending else None,
        }
        if receipts is not None:
            payload.update(receipts.payload())
        if handled and rating_answer:
            facts = build_facts(payload, state.pending)
            rating = facts.ratings_recorded[0] if facts.ratings_recorded else None
            acknowledgement = (
                f"Recorded your {rating.name} rating: {rating.value}."
                if rating
                else "Thanks for the update."
            )
            reply = safe_fixed(
                (acknowledgement + " " + question_text(state.pending)).strip(), facts
            )
            return self._save(repo, user.id, message.trace_id, Composed(reply, facts))
        if analysis.intent == "medical_ask":
            return self._save(
                repo,
                user.id,
                message.trace_id,
                Composed(MEDICAL_REFUSAL, build_facts(payload, state.pending)),
                calls=calls,
            )
        if experiment_error is not None:
            return self._save(
                repo,
                user.id,
                message.trace_id,
                Composed(experiment_error, build_facts(payload, None), fallback=True),
                calls=calls,
            )
        completed = repo.session.scalar(
            select(m.Experiment)
            .where(m.Experiment.user_id == user.id, m.Experiment.status == "completed")
            .order_by(m.Experiment.ended_on.desc(), m.Experiment.created_at.desc())
            .limit(1)
        )
        if completed is not None and completed.id != progress.last_verdict_id:
            result = compose_verdict(self.router, completed, ctx("composer_experiment"))
            progress.last_verdict_id = completed.id
            save_progress(repo, user.id, progress, state)
            return self._save(repo, user.id, message.trace_id, result, calls=calls)
        active = manager.active()
        if analysis.intent == "experiment" and active is not None:
            if (
                active.status == "proposed"
                or active.status == "accepted"
                or isinstance(state.pending, ConfirmExperiment)
            ):
                result = compose_protocol(
                    self.router,
                    active,
                    manager,
                    ctx("composer_experiment"),
                    abandon=progress.experiment_confirmation == "abandon",
                )
            elif instruction(active, manager) is not None:
                result = compose_instruction(
                    self.router, active, manager, ctx("composer_experiment"), state.pending
                )
            else:
                result = Composed(
                    "The scheduled days are finished. You can still fill missing entries "
                    "while the experiment remains open.",
                    build_facts(payload, None),
                )
            return self._save(repo, user.id, message.trace_id, result, calls=calls)
        if analysis.intent == "experiment":
            return self._save(
                repo,
                user.id,
                message.trace_id,
                Composed("The experiment is closed.", build_facts(payload, None)),
                calls=calls,
            )
        surfacer = InsightSurfacer(repo, user.id, clock=self.clock)
        surfacer.scan_if_needed()
        if (
            active is not None
            and instruction(active, manager) is not None
            and analysis.intent in {"checkin", "chitchat"}
        ):
            result = compose_instruction(
                self.router, active, manager, ctx("composer_experiment"), state.pending
            )
            return self._save(repo, user.id, message.trace_id, result, calls=calls)
        if active is None and not clarification and analysis.intent in {"checkin", "chitchat"}:
            surfaced = surfacer.surface()
            if surfaced is not None:
                result = compose_insight(
                    self.router, surfacer.snapshot(surfaced.id), ctx("composer_insight")
                )
                return self._save(repo, user.id, message.trace_id, result, calls=calls)
        tool_calls = 0
        pending = state.pending
        if analysis.intent == "ask_data":
            path = builder.path(base, "ask_data")
            loop = run_readonly_loop(self.router, tools, path, ctx("composer_answer"))
            tool_calls = loop.calls
            result_values: list[JsonValue] = []
            result_values.extend(loop.results)
            payload["tool_results"] = result_values
            pending = None
        result = compose(
            self.router,
            payload,
            ctx=ctx("composer_answer" if analysis.intent == "ask_data" else "composer_checkin"),
            pending=pending,
            clarification=clarification,
        )
        return self._save(
            repo, user.id, message.trace_id, result, calls=calls, tool_calls=tool_calls
        )

    @staticmethod
    def _apply(
        analysis: TurnAnalysis,
        tools: ToolRegistry,
        state: PendingState,
        progress: Progress,
        message_id: UUID,
    ) -> str | None:
        tools.execute(
            "log_events",
            {
                "events": [e.model_dump(mode="json") for e in analysis.events],
                "message_id": str(message_id),
            },
            allow_mutations=True,
        )
        pending = state.pending
        if isinstance(pending, OnboardingOutcomes) and analysis.setup_outcomes:
            result = tools.execute(
                "set_tracking",
                {"outcomes": [r.model_dump(mode="json") for r in analysis.setup_outcomes]},
                allow_mutations=True,
            )
            if "error" not in result:
                progress.onboarding = "exposures"
        if isinstance(pending, OnboardingExposures) and analysis.setup_exposures:
            result = tools.execute(
                "set_tracking",
                {"exposures": [name for name in analysis.setup_exposures]},
                allow_mutations=True,
            )
            if "error" not in result:
                progress.onboarding = "sleep"
        if isinstance(pending, OnboardingSleep) and analysis.setup_sleep is not None:
            tools.repo.set_tracking(tools.user_id, track_sleep=analysis.setup_sleep)
            progress.onboarding = "done"
        tracked = {r.name for r in tools.repo.get_tracking(tools.user_id).outcomes}
        for rating in analysis.ratings:
            name = normalize(rating.outcome).canonical
            if name in tracked:
                tools.repo.upsert_rating(
                    tools.user_id,
                    tools.day + timedelta(days=rating.relative_day),
                    name,
                    rating.value,
                )
        if pending is not None and analysis.skip:
            skip_pending(pending, False, progress, tools, message_id)
            state.pending = None
        elif isinstance(pending, ExposureChecklist) and (
            analysis.checklist_yes or analysis.checklist_none
        ):
            current = tools.repo.session.get(m.Message, message_id)
            assert current is not None
            if checklist_answer_supported(
                analysis.checklist_yes, analysis.checklist_none, current.content
            ):
                record_checklist(
                    tools,
                    pending,
                    [] if analysis.checklist_none else analysis.checklist_yes,
                    message_id,
                )
                state.pending = None
        if (
            isinstance(pending, ExperimentAdherence)
            and analysis.adherence is not None
            and not analysis.skip
        ):
            record_adherence(tools, pending, analysis.adherence)
            state.pending = None
        if analysis.experiment_action is not None:
            manager = ExperimentManager(tools.repo, tools.user_id, clock=tools.clock)
            try:
                if analysis.experiment_action == "start":
                    manager.propose(exposure=analysis.experiment_target)
                    state.pending = tools.repo.get_state(tools.user_id).pending
                    progress.experiment_confirmation = "accept"
                elif analysis.experiment_action == "accept":
                    if (
                        not isinstance(state.pending, ConfirmExperiment)
                        or progress.experiment_confirmation != "accept"
                    ):
                        raise ExperimentError(
                            "confirmation_required", "Please confirm a current proposal first."
                        )
                    manager.respond(state.pending.experiment_id, "accept")
                    state.pending = None
                    progress.experiment_confirmation = None
                else:
                    row = manager.active()
                    if row is None:
                        raise ExperimentError("not_found", "No current experiment was found.", 404)
                    manager.request_abandon(row.id)
                    state.pending = tools.repo.get_state(tools.user_id).pending
                    progress.experiment_confirmation = "abandon"
            except ExperimentError as error:
                return str(error)
        return None

    @staticmethod
    def _save(
        repo: Repository,
        user_id: UUID,
        trace_id: UUID,
        result: Composed,
        *,
        calls: int = 0,
        tool_calls: int = 0,
        limited: bool = False,
    ) -> ChatResult:
        repo.add_message(
            user_id, MessageInput(role="assistant", content=result.text, trace_id=trace_id)
        )
        return ChatResult(
            result.text,
            trace_id,
            result.facts,
            limited=limited,
            analyzer_calls=calls,
            tool_calls=tool_calls,
            regenerated=result.regenerated,
            fallback=result.fallback,
        )

    def _emergency(
        self,
        repo: Repository,
        user_id: UUID,
        message_id: UUID,
        trace_id: UUID,
        category: str,
        source: str,
        calls: int = 0,
    ) -> ChatResult:
        repo.session.add(
            m.SafetyEvent(user_id=user_id, message_id=message_id, category=category, source=source)
        )
        return self._save(
            repo,
            user_id,
            trace_id,
            Composed(ESCALATION, Facts(numbers=(Decimal(988),)), fallback=True),
            calls=calls,
        )

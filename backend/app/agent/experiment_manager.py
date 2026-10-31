"""User-scoped deterministic experiment lifecycle and immutable verdict snapshots."""

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select

from app.agent.progress import load_progress, save_progress
from app.config import EXPERIMENT_GRACE_DAYS, PROPOSAL_EXPIRY_DAYS
from app.db import models as m
from app.db.repos import Repository
from app.domain.clock import today
from app.domain.normalize import normalize
from app.domain.schemas import ConfirmExperiment
from app.stats.experiment import (
    DayObservation,
    DayPlan,
    ExperimentProtocol,
    check_eligibility,
    compute_verdict,
    make_protocol,
    schedule,
)

JSON = TypeAdapter(dict[str, JsonValue])
PROTOCOL = TypeAdapter(ExperimentProtocol)
ACTIVE = ("proposed", "accepted", "baseline", "running")


class ExperimentError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code, self.status_code = code, status_code
        super().__init__(message)


class ExperimentManager:
    def __init__(
        self,
        repo: Repository,
        user_id: UUID,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo, self.user_id, self.clock = repo, user_id, clock

    def day(self) -> date:
        return today(self.repo._user(self.user_id), now=self.clock())

    def logical_now(self) -> datetime:
        user = self.repo._user(self.user_id)
        now = self.clock().astimezone(ZoneInfo(user.tz))
        return datetime.combine(self.day(), now.timetz()).astimezone(UTC)

    def _owned(self, experiment_id: UUID) -> m.Experiment:
        row = self.repo.session.scalar(
            select(m.Experiment)
            .where(m.Experiment.user_id == self.user_id, m.Experiment.id == experiment_id)
            .with_for_update()
        )
        if row is None:
            raise ExperimentError("not_found", "Experiment not found.", 404)
        return row

    def _confirmation(self, row: m.Experiment, action: str | None) -> None:
        progress, state = load_progress(self.repo, self.user_id, self.day())
        if action is not None:
            state.pending = ConfirmExperiment(type="confirm_experiment", experiment_id=row.id)
        elif isinstance(state.pending, ConfirmExperiment) and state.pending.experiment_id == row.id:
            state.pending = None
        progress.experiment_confirmation = (
            "abandon" if action == "abandon" else "accept" if action == "accept" else None
        )
        save_progress(self.repo, self.user_id, progress, state)

    def active(self) -> m.Experiment | None:
        return self.repo.session.scalar(
            select(m.Experiment)
            .where(m.Experiment.user_id == self.user_id, m.Experiment.status.in_(ACTIVE))
            .with_for_update()
        )

    def advance(self) -> m.Experiment | None:
        row = self.active()
        if row is None:
            return None
        day = self.day()
        if row.status == "proposed":
            user = self.repo._user(self.user_id)
            proposed = row.created_at.astimezone(ZoneInfo(user.tz)).date()
            if day >= proposed + timedelta(days=PROPOSAL_EXPIRY_DAYS):
                row.status, row.end_reason, row.ended_on = "abandoned", "expired", day
                self._confirmation(row, None)
            return row
        # Legacy/scaffold records without an accepted schedule cannot be advanced.
        if row.started_on is None:
            return row
        plans = schedule(PROTOCOL.validate_python(row.protocol))
        if row.status == "accepted" and day >= plans[0].date:
            row.status = "baseline"
        if row.status == "baseline" and day >= plans[2].date:
            row.status = "running"
        if row.status == "running" and (
            day >= plans[-1].date + timedelta(days=EXPERIMENT_GRACE_DAYS)
            or self._all_filled(row, plans)
        ):
            self._complete(row, plans)
        self.repo.session.flush()
        return row

    def propose(
        self,
        *,
        exposure: str | None = None,
        outcome: str | None = None,
        pattern_id: UUID | None = None,
        experiment_id: UUID | None = None,
    ) -> m.Experiment:
        self.repo._user(self.user_id, lock=True)
        self.advance()
        if self.active() is not None:
            raise ExperimentError("already_active", "An experiment is already active.")
        if pattern_id is not None:
            pattern = self.repo.session.scalar(
                select(m.Pattern).where(
                    m.Pattern.id == pattern_id, m.Pattern.user_id == self.user_id
                )
            )
            if pattern is None:
                raise ExperimentError("not_found", "Pattern not found.", 404)
            exposure, outcome = pattern.exposure, pattern.outcome
        if not exposure:
            raise ExperimentError("missing_target", "Choose an existing tracked exposure.", 400)
        exposure = normalize(exposure).canonical
        tracking = self.repo.get_tracking(self.user_id)
        done = [
            row.local_date
            for row in self.repo.latest_events(self.user_id, date.min, self.day())
            if row.name == exposure and row.status == "done"
        ]
        eligible = check_eligibility(
            exposure,
            category=normalize(exposure).category,
            tracked=exposure in {r.name for r in tracking.exposures},
            done_dates=done,
        )
        if not eligible.eligible:
            raise ExperimentError(
                eligible.reason or "ineligible",
                "This exposure is not eligible for an experiment. "
                "Please discuss it with a clinician.",
                400,
            )
        outcomes = {r.name for r in tracking.outcomes}
        target = normalize(outcome).canonical if outcome else next(iter(sorted(outcomes)), None)
        if target not in outcomes:
            raise ExperimentError("untracked_outcome", "Choose a tracked outcome.", 400)
        assert target is not None
        experiment_id = experiment_id or uuid4()
        protocol = make_protocol(
            str(self.user_id), str(experiment_id), exposure=exposure, outcome=target
        )
        row = m.Experiment(
            id=experiment_id,
            user_id=self.user_id,
            exposure=exposure,
            outcome=target,
            protocol=JSON.validate_python(PROTOCOL.dump_python(protocol, mode="json")),
            seed=protocol.seed,
            pattern_id=pattern_id,
            created_at=self.logical_now(),
        )
        self.repo.session.add(row)
        self.repo.session.flush()
        self._confirmation(row, "accept")
        return row

    def request_abandon(self, experiment_id: UUID) -> m.Experiment:
        self.advance()
        row = self._owned(experiment_id)
        if row.status not in ACTIVE:
            raise ExperimentError("terminal", "The experiment has already ended.")
        self._confirmation(row, "abandon")
        return row

    def respond(self, experiment_id: UUID, action: str, *, confirmed: bool = False) -> m.Experiment:
        self.repo._user(self.user_id, lock=True)
        self.advance()
        row = self._owned(experiment_id)
        progress, state = load_progress(self.repo, self.user_id, self.day())
        pending = (
            isinstance(state.pending, ConfirmExperiment) and state.pending.experiment_id == row.id
        )
        if action not in {"accept", "abandon"} or (
            not confirmed and (not pending or progress.experiment_confirmation != action)
        ):
            raise ExperimentError(
                "confirmation_required", "Please confirm the pending experiment action."
            )
        if action == "accept":
            if row.status != "proposed":
                raise ExperimentError(
                    "illegal_transition", "Only a current proposal can be accepted."
                )
            from dataclasses import replace

            protocol = replace(
                PROTOCOL.validate_python(row.protocol), start_date=self.day() + timedelta(days=1)
            )
            row.protocol = JSON.validate_python(PROTOCOL.dump_python(protocol, mode="json"))
            row.status, row.accepted_at, row.started_on = (
                "accepted",
                self.logical_now(),
                protocol.start_date,
            )
            self.repo.session.add_all(
                [
                    m.ExperimentDay(
                        experiment_id=row.id, date=p.date, phase=p.phase, washout=p.washout
                    )
                    for p in schedule(protocol)
                ]
            )
        else:
            if row.status not in ACTIVE:
                raise ExperimentError("terminal", "The experiment has already ended.")
            row.status, row.end_reason, row.ended_on = "abandoned", "user", self.day()
        self._confirmation(row, None)
        self.repo.session.flush()
        return row

    def record_day(
        self,
        experiment_id: UUID,
        day: date,
        adherence: bool | None,
        *,
        outcome_value: int | None = None,
    ) -> m.ExperimentDay:
        self.advance()
        row = self._owned(experiment_id)
        if row.status in {"completed", "abandoned"}:
            raise ExperimentError(
                "terminal", "The experiment has ended; its snapshot cannot be changed."
            )
        if day > self.day():
            raise ExperimentError("future_day", "Future experiment days cannot be recorded.", 400)
        if adherence is not None and not isinstance(adherence, bool):
            raise ExperimentError(
                "invalid_adherence", "Adherence must be true, false, or unknown.", 400
            )
        plan = self.repo.session.scalar(
            select(m.ExperimentDay).where(
                m.ExperimentDay.experiment_id == row.id, m.ExperimentDay.date == day
            )
        )
        if plan is None:
            raise ExperimentError(
                "not_scheduled", "This date is outside the accepted schedule.", 400
            )
        plan.adherence = adherence
        if outcome_value is not None:
            self.repo.upsert_rating(self.user_id, day, row.outcome, outcome_value)
        self.repo.session.flush()
        self.advance()
        return plan

    def evaluate(self, experiment_id: UUID) -> dict[str, JsonValue]:
        self.advance()
        row = self._owned(experiment_id)
        if row.status != "completed" or row.verdict is None:
            raise ExperimentError("not_complete", "The experiment is not complete yet.")
        return deepcopy(row.verdict)

    def _all_filled(self, row: m.Experiment, plans: list[DayPlan]) -> bool:
        analysis = {p.date for p in plans if p.analysis}
        adherence = {
            p.date
            for p in self.repo.session.scalars(
                select(m.ExperimentDay).where(
                    m.ExperimentDay.experiment_id == row.id, m.ExperimentDay.adherence.is_not(None)
                )
            )
        }
        ratings = {
            r.local_date
            for r in self.repo.list_ratings(self.user_id, plans[0].date, plans[-1].date)
            if r.outcome_name == row.outcome
        }
        return analysis <= adherence & ratings

    def _complete(self, row: m.Experiment, plans: list[DayPlan]) -> None:
        if row.verdict is None:
            adherence = {
                p.date: p.adherence
                for p in self.repo.session.scalars(
                    select(m.ExperimentDay).where(m.ExperimentDay.experiment_id == row.id)
                )
            }
            ratings = {
                r.local_date: r.value
                for r in self.repo.list_ratings(self.user_id, plans[0].date, plans[-1].date)
                if r.outcome_name == row.outcome
            }
            outcome = self.repo.session.scalar(
                select(m.TrackedOutcome).where(
                    m.TrackedOutcome.user_id == self.user_id, m.TrackedOutcome.name == row.outcome
                )
            )
            assert outcome is not None
            verdict = compute_verdict(
                [
                    DayObservation(
                        p.date,
                        p.phase,
                        p.block,
                        ratings.get(p.date),
                        adherence.get(p.date),
                        p.washout,
                    )
                    for p in plans
                ],
                direction_better=outcome.direction_better,
                seed=row.seed,
            )
            row.verdict = JSON.validate_python(verdict)
        row.status, row.ended_on = "completed", self.day()
        self._confirmation(row, None)

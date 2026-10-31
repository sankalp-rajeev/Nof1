"""Pinned synthetic history and deterministic demo time advancement; no LLM imports."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.agent.experiment_manager import PROTOCOL, ExperimentError, ExperimentManager
from app.agent.insights import InsightSurfacer
from app.agent.progress import Progress, save_progress
from app.db import models as m
from app.db.repos import Repository
from app.domain.clock import today
from app.domain.normalize import normalize
from app.domain.schemas import EventInput, PendingState
from app.domain.timeutil import map_event_time
from sim.config import EXPOSURES, OUTCOME, START_DATE
from sim.demo import DEMO_SEED, demo_world
from sim.world import SimDay, generate_world, simulate_experiment

DEMO_HISTORY_DAYS = 45


def store_day(repo: Repository, user_id: UUID, day: SimDay, *, force: bool = False) -> None:
    if not day.observed and not force:
        return
    user = repo._user(user_id)
    mapped = map_event_time(day.date, user.tz)
    repo.upsert_checkin(user_id, day.date, completed=True, checklist_answered=True)
    repo.upsert_rating(user_id, day.date, OUTCOME, int(day.y))
    for name, value in zip(EXPOSURES[:5], day.reported_exposures[:5], strict=True):
        repo.add_event(
            user_id,
            EventInput(
                name=name,
                kind=normalize(name).kind or "life",
                status="done" if value else "skipped",
                source="demo",
            ),
            ts=mapped.ts,
            local_date=day.date,
        )
    repo.add_event(
        user_id,
        EventInput(kind="sleep", name="sleep", value=day.sleep_hours, unit="hours", source="demo"),
        ts=mapped.ts,
        local_date=day.date,
    )


def load_demo(repo: Repository, user_id: UUID, clock: Callable[[], datetime]) -> None:
    user = repo._user(user_id, lock=True)
    if user.is_demo:
        return
    for model in (
        m.Message,
        m.Event,
        m.OutcomeRating,
        m.Checkin,
        m.TrackedOutcome,
        m.TrackedExposure,
        m.Experiment,
        m.Pattern,
    ):
        if (
            repo.session.scalar(select(model.id).where(model.user_id == user_id).limit(1))
            is not None
        ):
            raise ExperimentError(
                "nonempty_account", "Demo history requires an empty account.", 409
            )
    real_day = today(user, now=clock())
    world = demo_world()
    user.is_demo = True
    user.clock_offset_days = (world.days[-1].date - real_day).days
    # Demo data remains real-class for provider-policy purposes.
    repo.set_tracking(
        user_id, outcomes=[(OUTCOME, "lower")], exposures=list(EXPOSURES[:5]), track_sleep=True
    )
    for day in world.days:
        store_day(repo, user_id, day, force=day.date == world.days[-1].date)
    save_progress(
        repo, user_id, Progress(date=world.days[-1].date, onboarding="done"), PendingState()
    )
    InsightSurfacer(repo, user_id, clock=clock).scan_if_needed()
    InsightSurfacer(repo, user_id, clock=clock).surface()


def advance_demo(repo: Repository, user_id: UUID, days: int, clock: Callable[[], datetime]) -> None:
    user = repo._user(user_id, lock=True)
    if not user.is_demo:
        raise ExperimentError("demo_only", "Simulated time is available only for demo users.", 403)
    manager = ExperimentManager(repo, user_id, clock=clock)
    start = manager.day()
    for offset in range(1, days + 1):
        target = start + timedelta(days=offset)
        # Read the schedule before changing the logical clock; completing a day
        # must happen only after its synthetic observations have been persisted.
        active = manager.active()
        user.clock_offset_days += 1
        simulated = None
        if (
            active is not None
            and active.started_on is not None
            and active.status in {"accepted", "baseline", "running"}
        ):
            protocol = PROTOCOL.validate_python(active.protocol)
            history = generate_world(DEMO_SEED, days=(active.started_on - START_DATE).days)
            experiment = simulate_experiment(history, protocol, 1.0)
            for day in experiment.days:
                if day.date == target:
                    simulated = day
                    break
        if simulated is None:
            simulated = generate_world(DEMO_SEED, days=(target - START_DATE).days + 1).days[-1]
        store_day(repo, user_id, simulated, force=True)
        repo.session.flush()
        if active is not None and active.started_on is not None:
            plan = repo.session.scalar(
                select(m.ExperimentDay).where(
                    m.ExperimentDay.experiment_id == active.id, m.ExperimentDay.date == target
                )
            )
            if plan is not None and active.status not in {"completed", "abandoned"}:
                plan.adherence = None if plan.phase == "baseline" else True
        manager.advance()
    InsightSurfacer(repo, user_id, clock=clock).scan_if_needed()

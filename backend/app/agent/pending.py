"""Deterministic pending answers and one-question priority; no provider access."""

import re
from datetime import date
from uuid import UUID

from sqlalchemy import func, select

from app.agent.analyzer import ExtractedEvent
from app.agent.experiment_manager import ExperimentManager
from app.agent.progress import Progress
from app.agent.tools.registry import LogEventsArgs, ToolRegistry
from app.db import models as m
from app.db.repos import Repository
from app.domain.normalize import load_aliases, normalize
from app.domain.schemas import (
    ConfirmExperiment,
    ConfirmTrack,
    ExperimentAdherence,
    ExposureChecklist,
    OnboardingExposures,
    OnboardingOutcomes,
    OnboardingSleep,
    Pending,
    PendingState,
    RateOutcome,
    SleepHours,
)

YES = frozenset({"yes", "y", "yeah", "yep", "sure"})
NO = frozenset({"no", "n", "nope"})
SKIP = frozenset({"skip", "none"})


def checklist_answer_supported(yes: list[str], none: bool, current_text: str) -> bool:
    """A pending checklist is not evidence: require this turn to report its answer."""
    text = current_text.casefold().replace("’", "'")
    if none:
        return bool(
            re.search(
                r"\b(?:none|neither|nothing|no exposures|(?:didn't|did not|haven't) "
                r"(?:take|have|use|do|had|taken) any)\b",
                text,
            )
        )
    if not yes:
        return False
    for name in yes:
        canonical = normalize(name).canonical
        names = {canonical} | {
            alias.alias for alias in load_aliases() if alias.canonical == canonical
        }
        if not any(re.search(r"\b" + re.escape(alias) + r"\b", text) for alias in names):
            return False
    return True


def record_checklist(
    tools: ToolRegistry, pending: ExposureChecklist, yes: list[str], message_id: UUID
) -> None:
    present = {normalize(name).canonical for name in yes}
    events = [
        ExtractedEvent(
            kind=normalize(name).kind or "life",
            name=name,
            status="done" if name in present else "skipped",
        )
        for name in pending.names
    ]
    # Same validated persistence as ordinary events, with an explicit checklist source.
    result = tools.log_events(LogEventsArgs(events=events, message_id=message_id))
    ids = result["event_ids"]
    assert isinstance(ids, list)
    for event_id in ids:
        row = tools.repo.session.get(m.Event, UUID(str(event_id)))
        assert row is not None
        row.source = "checklist"
    tools.repo.upsert_checkin(tools.user_id, pending.date, checklist_answered=True)


def record_adherence(tools: ToolRegistry, pending: ExperimentAdherence, value: bool) -> None:
    if pending.date != tools.day:
        return
    ExperimentManager(tools.repo, tools.user_id, clock=tools.clock).record_day(
        pending.experiment_id, pending.date, value
    )


def consume(
    text: str, state: PendingState, progress: Progress, tools: ToolRegistry, message_id: UUID
) -> bool:
    pending = state.pending
    if pending is None:
        return False
    word = text.strip().casefold().rstrip(".!?")
    if isinstance(pending, RateOutcome) and re.fullmatch(r"\d+", word) and 0 <= int(word) <= 10:
        tracked = {r.name for r in tools.repo.get_tracking(tools.user_id).outcomes}
        if pending.outcome not in tracked:
            return False
        tools.repo.upsert_rating(tools.user_id, tools.day, pending.outcome, int(word))
    elif (
        isinstance(pending, SleepHours)
        and re.fullmatch(r"\d+(?:\.\d+)?", word)
        and 0 <= float(word) <= 16
    ):
        tools.log_events(
            LogEventsArgs(
                events=[
                    ExtractedEvent(kind="sleep", name="sleep", value=float(word), unit="hours")
                ],
                message_id=message_id,
            )
        )
    elif isinstance(pending, OnboardingSleep) and word in YES | NO:
        tools.repo.set_tracking(tools.user_id, track_sleep=word in YES)
        progress.onboarding = "done"
    elif isinstance(pending, ConfirmTrack) and word in YES | NO:
        tracking = tools.repo.get_tracking(tools.user_id)
        if word in YES:
            names = [r.name for r in tracking.exposures]
            if pending.name not in names and len(names) < 5:
                tools.repo.set_tracking(tools.user_id, exposures=names + [pending.name])
        else:
            row = tools.repo.session.scalar(
                select(m.TrackedExposure).where(
                    m.TrackedExposure.user_id == tools.user_id,
                    m.TrackedExposure.name == pending.name,
                )
            )
            if row is None:
                tools.repo.session.add(
                    m.TrackedExposure(
                        user_id=tools.user_id, name=pending.name, active=False, declined=True
                    )
                )
            else:
                row.active, row.declined = False, True
    elif isinstance(pending, ConfirmExperiment) and word in YES | NO:
        manager = ExperimentManager(tools.repo, tools.user_id, clock=tools.clock)
        action = progress.experiment_confirmation or "accept"
        if word in YES:
            manager.respond(pending.experiment_id, action)
        elif action == "accept":
            manager.respond(pending.experiment_id, "abandon", confirmed=True)
        else:
            manager._confirmation(manager._owned(pending.experiment_id), None)
        progress.experiment_confirmation = None
    elif isinstance(pending, ExperimentAdherence) and word in YES | NO:
        record_adherence(tools, pending, word in YES)
    elif word in SKIP:
        skip_pending(pending, word == "none", progress, tools, message_id)
    else:
        return False
    state.pending = None
    return True


def skip_pending(
    pending: Pending, none: bool, progress: Progress, tools: ToolRegistry, message_id: UUID
) -> None:
    if isinstance(pending, RateOutcome):
        if pending.outcome not in progress.skipped_outcomes:
            progress.skipped_outcomes.append(pending.outcome)
    elif isinstance(pending, SleepHours):
        progress.sleep_skipped = True
    elif isinstance(pending, ExposureChecklist):
        if none:
            record_checklist(tools, pending, [], message_id)
        else:
            progress.checklist_skipped = True
    elif isinstance(pending, OnboardingOutcomes):
        tools.repo.set_tracking(tools.user_id, outcomes=[])
        progress.onboarding = "exposures"
    elif isinstance(pending, OnboardingExposures):
        tools.repo.set_tracking(tools.user_id, exposures=[])
        progress.onboarding = "sleep"
    elif isinstance(pending, OnboardingSleep):
        tools.repo.set_tracking(tools.user_id, track_sleep=False)
        progress.onboarding = "done"


def next_question(
    repo: Repository, user_id: UUID, day: date, progress: Progress, state: PendingState
) -> Pending | None:
    if isinstance(state.pending, ConfirmExperiment):
        return state.pending
    if progress.onboarding != "done":
        stages: dict[str, Pending] = {
            "outcomes": OnboardingOutcomes(type="onboarding_outcomes"),
            "exposures": OnboardingExposures(type="onboarding_exposures"),
            "sleep": OnboardingSleep(type="onboarding_sleep"),
        }
        return stages[progress.onboarding or "outcomes"]
    tracking = repo.get_tracking(user_id)
    ratings = {r.outcome_name for r in repo.list_ratings(user_id, day, day)}
    missing = [
        r.name
        for r in tracking.outcomes
        if r.name not in ratings and r.name not in progress.skipped_outcomes
    ]
    repo.upsert_checkin(user_id, day, completed=not missing)
    if missing:
        return RateOutcome(type="rate_outcome", outcome=missing[0])
    if (
        tracking.track_sleep
        and not progress.sleep_skipped
        and not any(
            e.kind == "sleep" and e.value is not None for e in repo.latest_events(user_id, day, day)
        )
    ):
        return SleepHours(type="sleep_hours", date=day)
    checkin = repo.session.scalar(
        select(m.Checkin).where(m.Checkin.user_id == user_id, m.Checkin.local_date == day)
    )
    if (
        tracking.exposures
        and checkin is not None
        and not checkin.checklist_answered
        and not progress.checklist_skipped
    ):
        stated = {
            row.name
            for row in repo.latest_events(user_id, day, day)
            if row.kind not in {"symptom", "sleep"}
        }
        remaining = [row.name for row in tracking.exposures if row.name not in stated]
        if remaining:
            return ExposureChecklist(type="exposure_checklist", date=day, names=remaining)
        repo.upsert_checkin(user_id, day, checklist_answered=True)
    adherence = repo.session.scalar(
        select(m.ExperimentDay)
        .join(m.Experiment)
        .where(
            m.Experiment.user_id == user_id,
            m.Experiment.status.in_(["accepted", "baseline", "running"]),
            m.ExperimentDay.date == day,
            m.ExperimentDay.phase.in_(["on", "off"]),
            m.ExperimentDay.adherence.is_(None),
        )
    )
    if adherence is not None:
        return ExperimentAdherence(
            type="experiment_adherence", experiment_id=adherence.experiment_id, date=day
        )
    if state.pending is not None and state.pending.type in {"confirm_track", "confirm_experiment"}:
        return state.pending
    if len(tracking.exposures) < 5 and progress.suggested_on != day:
        known = set(
            repo.session.scalars(
                select(m.TrackedExposure.name).where(m.TrackedExposure.user_id == user_id)
            )
        )
        candidates = repo.session.execute(
            select(m.Event.name)
            .where(m.Event.user_id == user_id, m.Event.status == "done")
            .group_by(m.Event.name)
            .having(func.count(func.distinct(m.Event.local_date)) >= 3)
            .order_by(m.Event.name)
        )
        for (name,) in candidates:
            if name not in known and normalize(name).category in {"supplement", "food", "habit"}:
                progress.suggested_on = day
                return ConfirmTrack(type="confirm_track", name=name)
    return None


def question_text(pending: Pending | None) -> str:
    if pending is None:
        return ""
    if isinstance(pending, OnboardingOutcomes):
        return "What outcomes would you like to track, and is higher better for any of them?"
    if isinstance(pending, OnboardingExposures):
        return "What do you take or do that you want to keep an eye on? You can say none."
    if isinstance(pending, OnboardingSleep):
        return "Would you like to log sleep hours daily?"
    if isinstance(pending, RateOutcome):
        return f"How was {pending.outcome} today, from 0 to 10?"
    if isinstance(pending, SleepHours):
        return "How many hours did you sleep?"
    if isinstance(pending, ExposureChecklist):
        return (
            "Quick check for today: "
            + ", ".join(pending.names)
            + ". Which did you have? Anything you don't mention counts as no."
        )
    if isinstance(pending, ExperimentAdherence):
        return "Did you follow today's accepted experiment plan?"
    if isinstance(pending, ConfirmTrack):
        return f"Would you like to track {pending.name}?"
    return "Would you like to confirm the proposed experiment?"

"""JSON views of user-scoped records and logical experiment days."""

from collections.abc import Iterable
from datetime import date, timedelta
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select

from app.agent.experiment_manager import PROTOCOL, ExperimentManager
from app.agent.pending import question_text
from app.agent.progress import load_progress
from app.agent.safety.templates import ESCALATION
from app.api.runtime import Runtime
from app.config import EXPERIMENT_LIMITATION
from app.db import models as m
from app.db.repos import Repository
from app.domain.clock import today
from app.domain.normalize import normalize
from app.stats.experiment import check_eligibility, schedule

JSON = TypeAdapter(dict[str, JsonValue])


def row_json(row: m.Base) -> dict[str, JsonValue]:
    return JSON.validate_python(
        jsonable_encoder(
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
        )
    )


def chat_view(repo: Repository, user_id: UUID, reply: m.Message) -> dict[str, JsonValue]:
    saved = reply.response_payload or {}
    if "reply" in saved:
        return saved
    metadata = saved.get("_result", {})
    assert isinstance(metadata, dict)
    message_id = repo.session.scalar(
        select(m.Message.id).where(
            m.Message.user_id == user_id,
            m.Message.trace_id == reply.trace_id,
            m.Message.role == "user",
        )
    )
    events: list[JsonValue] = [
        row_json(row)
        for row in repo.session.scalars(
            select(m.Event).where(m.Event.user_id == user_id, m.Event.message_id == message_id)
        )
    ]
    pending = repo.get_state(user_id).pending
    payload: dict[str, JsonValue] = {
        "reply": reply.content,
        "trace_id": str(reply.trace_id),
        "events_logged": events,
        "pending_question": metadata.get(
            "pending_question", question_text(pending) if pending else None
        ),
        "limited_mode": metadata.get("limited_mode", False),
        "safety": {"red_flag": reply.content == ESCALATION},
        "new_insight": metadata.get("new_insight"),
        "experiment_prompt": metadata.get("experiment_prompt"),
    }
    reply.response_payload = payload
    return payload


def tracking_view(repo: Repository, user_id: UUID, runtime: Runtime) -> dict[str, JsonValue]:
    user = repo._user(user_id)
    result = repo.get_tracking(user_id).model_dump(mode="json")
    result.update(
        {
            "is_demo": user.is_demo,
            "today": today(user, now=runtime.clock()).isoformat(),
            "clock_offset_days": user.clock_offset_days,
        }
    )
    return JSON.validate_python(result)


def timeline_view(
    repo: Repository, user_id: UUID, runtime: Runtime, days: int = 14
) -> dict[str, JsonValue]:
    day = today(repo._user(user_id), now=runtime.clock())
    start = day - timedelta(days=days - 1)
    events = repo.latest_events(user_id, start, day)
    ratings = repo.list_ratings(user_id, start, day)
    checkins = {
        row.local_date: row
        for row in repo.session.scalars(
            select(m.Checkin).where(
                m.Checkin.user_id == user_id,
                m.Checkin.local_date >= start,
                m.Checkin.local_date <= day,
            )
        )
    }
    output: list[JsonValue] = []
    for index in range(days):
        current = start + timedelta(days=index)
        checkin = checkins.get(current)
        output.append(
            {
                "date": current.isoformat(),
                "events": [row_json(row) for row in events if row.local_date == current],
                "ratings": [row_json(row) for row in ratings if row.local_date == current],
                "checklist_answered": bool(checkin and checkin.checklist_answered),
                "completed": bool(checkin and checkin.completed),
            }
        )
    return {"today": day.isoformat(), "days": output}


def experiment_view(
    repo: Repository, user_id: UUID, runtime: Runtime, row: m.Experiment | None = None
) -> dict[str, JsonValue]:
    manager = ExperimentManager(repo, user_id, clock=runtime.clock)
    manager.advance()
    if row is None:
        row = repo.session.scalar(
            select(m.Experiment)
            .where(m.Experiment.user_id == user_id)
            .order_by(m.Experiment.created_at.desc())
            .limit(1)
        )
    day = manager.day()
    plans = (
        schedule(PROTOCOL.validate_python(row.protocol))
        if row is not None and row.started_on is not None
        else []
    )
    current = next((plan for plan in plans if plan.date == day), None)
    saved = (
        repo.session.scalar(
            select(m.ExperimentDay).where(
                m.ExperimentDay.experiment_id == row.id, m.ExperimentDay.date == day
            )
        )
        if row is not None
        else None
    )
    rating = next(
        (
            rating.value
            for rating in repo.list_ratings(user_id, day, day)
            if row is not None and rating.outcome_name == row.outcome
        ),
        None,
    )
    return JSON.validate_python(
        jsonable_encoder(
            {
                "experiment": row_json(row) if row is not None else None,
                "today": day,
                "today_plan": {
                    "date": current.date,
                    "phase": current.phase,
                    "washout": current.washout,
                    "adherence": saved.adherence if saved else None,
                    "outcome_value": rating,
                }
                if current
                else None,
                "progress": {"day": sum(plan.date <= day for plan in plans), "total": len(plans)},
                "schedule": [
                    {"date": plan.date, "phase": plan.phase, "washout": plan.washout}
                    for plan in plans
                ],
                "limitation": EXPERIMENT_LIMITATION,
            }
        )
    )


def insights_view(repo: Repository, user_id: UUID, runtime: Runtime) -> list[JsonValue]:
    progress, _ = load_progress(repo, user_id, today(repo._user(user_id), now=runtime.clock()))
    latest = progress.latest_run_id or repo.session.scalar(
        select(m.Pattern.run_id)
        .where(m.Pattern.user_id == user_id)
        .order_by(m.Pattern.computed_at.desc())
        .limit(1)
    )
    rows: Iterable[m.Pattern] = (
        repo.session.scalars(
            select(m.Pattern)
            .where(m.Pattern.user_id == user_id, m.Pattern.run_id == latest)
            .order_by(m.Pattern.p_adj, m.Pattern.pattern_key)
        )
        if latest
        else []
    )
    tracking = repo.get_tracking(user_id)
    events = repo.latest_events(user_id, date.min, today(repo._user(user_id), now=runtime.clock()))
    output: list[JsonValue] = []
    for row in rows:
        payload = row_json(row)
        eligible = check_eligibility(
            row.exposure,
            category=normalize(row.exposure).category,
            tracked=row.exposure in {e.name for e in tracking.exposures},
            done_dates=[
                e.local_date for e in events if e.name == row.exposure and e.status == "done"
            ],
        )
        payload["eligible"] = eligible.eligible
        payload["ineligible_reason"] = eligible.reason
        output.append(payload)
    return output

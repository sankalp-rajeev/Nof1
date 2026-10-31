"""JSON views of user-scoped records and logical experiment days."""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import JsonValue, TypeAdapter
from sqlalchemy import select

from app.agent.experiment_manager import PROTOCOL, ExperimentManager
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
    latest = repo.session.scalar(
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

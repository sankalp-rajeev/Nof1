"""Compact JSON tools with validation, savepoints, and read-only dispatch boundaries."""

import logging
from datetime import date
from time import monotonic
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.agent.analyzer import ExtractedEvent
from app.config import TIMELINE_ROW_LIMIT
from app.db import models as m
from app.db.repos import Repository
from app.domain.normalize import normalize
from app.domain.schemas import DomainModel, EventInput, Kind, OutcomeTracking, PatternRecord
from app.domain.timeutil import map_event_time

JSON = TypeAdapter(dict[str, JsonValue])
logger = logging.getLogger(__name__)


class LogEventsArgs(DomainModel):
    events: list[ExtractedEvent] = Field(max_length=40)
    message_id: UUID


class SetTrackingArgs(DomainModel):
    outcomes: list[OutcomeTracking] | None = Field(default=None, max_length=3)
    exposures: list[str] | None = Field(default=None, max_length=5)
    track_sleep: bool | None = None


class TimelineArgs(DomainModel):
    start: date
    end: date
    kinds: list[Kind] | None = None
    names: list[str] | None = None

    @model_validator(mode="after")
    def valid_window(self) -> "TimelineArgs":
        if self.start > self.end:
            raise ValueError("start must not follow end")
        return self


class InsightsArgs(DomainModel):
    max_items: int = Field(default=3, ge=1, le=20)


class EmptyArgs(DomainModel):
    pass


class ToolRegistry:
    schemas: ClassVar[dict[str, type[BaseModel]]] = {
        "log_events": LogEventsArgs,
        "set_tracking": SetTrackingArgs,
        "query_timeline": TimelineArgs,
        "get_insights": InsightsArgs,
        "get_experiment_status": EmptyArgs,
    }
    readonly: ClassVar[frozenset[str]] = frozenset(
        {"query_timeline", "get_insights", "get_experiment_status"}
    )

    def __init__(self, repo: Repository, user_id: UUID, day: date, trace_id: UUID) -> None:
        self.repo, self.user_id, self.day, self.trace_id = repo, user_id, day, trace_id

    def descriptions(self) -> list[dict[str, JsonValue]]:
        return [
            {
                "name": name,
                "description": getattr(self, name).__doc__ or "",
                "arguments": self.schemas[name].model_json_schema(),
            }
            for name in sorted(self.readonly)
        ]

    def execute(
        self, name: str, arguments: dict[str, JsonValue], *, allow_mutations: bool = False
    ) -> dict[str, JsonValue]:
        started = monotonic()
        result: dict[str, JsonValue]
        if name not in self.schemas or (name not in self.readonly and not allow_mutations):
            result = self.error("tool_not_allowed", "Choose an available read-only tool.")
        else:
            try:
                args = self.schemas[name].model_validate(arguments)
                with self.repo.session.begin_nested():
                    result = JSON.validate_python(getattr(self, name)(args))
            except (ValidationError, ValueError, SQLAlchemyError):
                result = self.error("invalid_arguments", "Use the tool's declared argument schema.")
        logger.info(
            "tool_call",
            extra={
                "trace_id": str(self.trace_id),
                "user_id": str(self.user_id),
                "tool": name if name in self.schemas else "unknown",
                "error": "error" in result,
                "latency_ms": (monotonic() - started) * 1000,
            },
        )
        return result

    @staticmethod
    def error(code: str, hint: str) -> dict[str, JsonValue]:
        return {
            "error": {"code": code, "message": "Tool request could not be applied.", "hint": hint}
        }

    def log_events(self, args: LogEventsArgs) -> dict[str, JsonValue]:
        """Persist validated events for the bound user (code only). Args: events and owned
        message_id. Names are normalized and bounded relative dates use the user's timezone.
        Returns event ids and applied count. Invalid kinds/dates/ownership return an error object.
        """
        user = self.repo.get_user(self.user_id)
        if user is None:
            raise ValueError("User not found")
        ids: list[JsonValue] = []
        for event in args.events:
            if event.kind == "sleep" and event.value is None:
                continue
            mapped = map_event_time(
                self.day, user.tz, relative_day=event.relative_day, time_of_day=event.time_of_day
            )
            data = EventInput.model_validate(
                event.model_dump(exclude={"relative_day", "time_of_day"})
            )
            saved = self.repo.add_event(
                self.user_id,
                data,
                ts=mapped.ts,
                local_date=mapped.local_date,
                message_id=args.message_id,
            )
            ids.append(str(saved.id))
        return {"event_ids": ids, "count": len(ids)}

    def set_tracking(self, args: SetTrackingArgs) -> dict[str, JsonValue]:
        """Set the bound user's tracking (code only). Optional outcomes have names and better
        directions; exposures are names; track_sleep is bool. Limits are three outcomes and
        five exposures. Returns current tracking or a validation error without partial updates.
        """
        state = self.repo.set_tracking(
            self.user_id,
            outcomes=[(r.name, r.direction_better) for r in args.outcomes]
            if args.outcomes is not None
            else None,
            exposures=args.exposures,
            track_sleep=args.track_sleep,
        )
        return JSON.validate_python(state.model_dump(mode="json"))

    def query_timeline(self, args: TimelineArgs) -> dict[str, JsonValue]:
        """Read the bound user's timeline. Args: inclusive ISO start/end dates, optional kinds
        and canonical/alias names. Returns at most 200 latest-per-date/name event rows and
        outcome ratings grouped by date, with truncation flag. Reversed/invalid dates return error.
        """
        names = {normalize(name).canonical for name in args.names} if args.names else None
        rows: list[dict[str, JsonValue]] = [
            {
                "date": r.local_date.isoformat(),
                "kind": r.kind,
                "name": r.name,
                "status": r.status,
                "value": r.value,
                "unit": r.unit,
                "severity": r.severity,
                "id": str(r.id),
            }
            for r in self.repo.latest_events(self.user_id, args.start, args.end)
            if (not args.kinds or r.kind in args.kinds) and (names is None or r.name in names)
        ]
        if not args.kinds or "symptom" in args.kinds:
            rows.extend(
                {
                    "date": r.local_date.isoformat(),
                    "kind": "rating",
                    "name": r.outcome_name,
                    "value": r.value,
                    "id": str(r.id),
                }
                for r in self.repo.list_ratings(self.user_id, args.start, args.end)
                if names is None or r.outcome_name in names
            )
        rows.sort(key=lambda row: (str(row["date"]), str(row["name"]), str(row["id"])))
        selected = rows[-TIMELINE_ROW_LIMIT:]
        grouped: dict[str, JsonValue] = {}
        for row in selected:
            key = str(row["date"])
            existing = grouped.setdefault(key, [])
            assert isinstance(existing, list)
            existing.append(row)
        return {"days": grouped, "truncated": len(rows) > TIMELINE_ROW_LIMIT}

    def get_insights(self, args: InsightsArgs) -> dict[str, JsonValue]:
        """Read latest-run patterns for the bound user. Optional max_items defaults to three.
        Returns tier, effect, pair counts, confounder and frozen data-point references. No rows
        yields an empty patterns list. This tool never scans, surfaces or changes patterns.
        """
        latest = self.repo.session.scalar(
            select(m.Pattern)
            .where(m.Pattern.user_id == self.user_id)
            .order_by(m.Pattern.computed_at.desc())
            .limit(1)
        )
        if latest is None:
            return {"patterns": []}
        rows = self.repo.session.scalars(
            select(m.Pattern)
            .where(m.Pattern.user_id == self.user_id, m.Pattern.run_id == latest.run_id)
            .order_by(m.Pattern.p_adj, m.Pattern.pattern_key)
            .limit(args.max_items)
        )
        return {
            "patterns": [
                JSON.validate_python(PatternRecord.model_validate(row).model_dump(mode="json"))
                for row in rows
            ]
        }

    def get_experiment_status(self, args: EmptyArgs) -> dict[str, JsonValue]:
        """Read the bound user's latest protocol and today's scheduled phase. Args: empty object.
        Returns status, phase, washout, days_left and protocol, or experiment=null. Does not
        propose, accept, abandon, advance, or evaluate an experiment.
        """
        experiment = self.repo.session.scalar(
            select(m.Experiment)
            .where(m.Experiment.user_id == self.user_id)
            .order_by(m.Experiment.created_at.desc())
            .limit(1)
        )
        if experiment is None:
            return {"experiment": None}
        days = list(
            self.repo.session.scalars(
                select(m.ExperimentDay)
                .where(m.ExperimentDay.experiment_id == experiment.id)
                .order_by(m.ExperimentDay.date)
            )
        )
        current = next((d for d in days if d.date == self.day), None)
        return {
            "experiment": {
                "id": str(experiment.id),
                "status": experiment.status,
                "phase": current.phase if current else None,
                "washout": current.washout if current else False,
                "days_left": sum(d.date >= self.day for d in days),
                "protocol": experiment.protocol,
            }
        }

"""Triggered scans and immutable surfaced evidence; observational language only."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import func, select

from app.agent.experiment_manager import ExperimentManager
from app.agent.progress import load_progress, save_progress
from app.config import INSIGHT_COOLDOWN_DAYS, INSIGHT_MIN_DAYS
from app.db import models as m
from app.db.repos import Repository
from app.domain.clock import today
from app.domain.schemas import PatternRecord
from app.stats.config import N_PERM
from app.stats.panel import ChecklistDay, PanelEvent, PanelRating, build_panel
from app.stats.patterns import scan_patterns

JSON = TypeAdapter(dict[str, JsonValue])


class InsightSurfacer:
    def __init__(
        self,
        repo: Repository,
        user_id: UUID,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        n_perm: int = N_PERM,
    ) -> None:
        self.repo, self.user_id, self.clock, self.n_perm = repo, user_id, clock, n_perm

    def scan_if_needed(self) -> UUID | None:
        user = self.repo._user(self.user_id)
        day = today(user, now=self.clock())
        checkins = list(
            self.repo.session.scalars(
                select(m.Checkin).where(
                    m.Checkin.user_id == self.user_id, m.Checkin.local_date <= day
                )
            )
        )
        if not any(c.local_date == day and (c.completed or c.checklist_answered) for c in checkins):
            return None
        ratings = self.repo.list_ratings(self.user_id, date.min, day)
        events = self.repo.latest_events(self.user_id, date.min, day)
        changed = (
            [r.updated_at for r in ratings]
            + [e.created_at for e in events if e.kind == "sleep" or e.source == "checklist"]
            + [c.created_at for c in checkins if c.checklist_answered]
        )
        progress, state = load_progress(self.repo, self.user_id, day)
        if not changed or (
            progress.scan_computed_at is not None and max(changed) <= progress.scan_computed_at
        ):
            return None
        tracking = self.repo.get_tracking(self.user_id)
        panel = build_panel(
            events=[
                PanelEvent(e.local_date, e.name, e.kind, e.status, e.created_at, e.value, str(e.id))
                for e in events
            ],
            ratings=[
                PanelRating(r.local_date, r.outcome_name, r.value, r.updated_at) for r in ratings
            ],
            checkins=[ChecklistDay(c.local_date, c.checklist_answered) for c in checkins],
            tracked_outcomes=[r.name for r in tracking.outcomes],
            tracked_exposures=[r.name for r in tracking.exposures],
            track_sleep=tracking.track_sleep,
        )
        if len(panel.dates) < INSIGHT_MIN_DAYS:
            return None
        result = scan_patterns(
            panel, user_id=str(self.user_id), purpose="app-scan", n_perm=self.n_perm
        )
        computed = self.repo.session.scalar(select(func.clock_timestamp()))
        assert isinstance(computed, datetime)
        run_id = uuid4()
        for pattern in result.patterns:
            payload = asdict(pattern)
            payload["data_points"] = [
                JSON.validate_json(TypeAdapter(dict[str, object]).dump_json(asdict(point)))
                for point in pattern.data_points
            ]
            self.repo.session.add(
                m.Pattern(user_id=self.user_id, run_id=run_id, computed_at=computed, **payload)
            )
        progress.scan_computed_at, progress.latest_run_id = computed, run_id
        save_progress(self.repo, self.user_id, progress, state)
        return run_id

    def surface(self) -> m.Pattern | None:
        day = today(self.repo._user(self.user_id), now=self.clock())
        now = ExperimentManager(self.repo, self.user_id, clock=self.clock).logical_now()
        progress, _ = load_progress(self.repo, self.user_id, day)
        previous = self.repo.session.scalar(
            select(m.Pattern)
            .where(m.Pattern.user_id == self.user_id, m.Pattern.surfaced_at.is_not(None))
            .order_by(m.Pattern.surfaced_at.desc(), m.Pattern.id.desc())
            .limit(1)
        )
        if (
            previous is not None
            and previous.surfaced_at is not None
            and now - previous.surfaced_at < timedelta(days=INSIGHT_COOLDOWN_DAYS)
        ):
            return None
        run_id = progress.latest_run_id
        if run_id is None:
            latest = self.repo.session.scalar(
                select(m.Pattern)
                .where(m.Pattern.user_id == self.user_id)
                .order_by(m.Pattern.computed_at.desc())
                .limit(1)
            )
            run_id = latest.run_id if latest else None
        if run_id is None:
            return None
        rows = self.repo.session.scalars(
            select(m.Pattern)
            .where(m.Pattern.user_id == self.user_id, m.Pattern.run_id == run_id)
            .order_by(m.Pattern.p_adj, func.abs(m.Pattern.effect).desc(), m.Pattern.pattern_key)
        )
        rank = {"weak": 0, "moderate": 1}
        for row in rows:
            last = self.repo.session.scalar(
                select(m.Pattern)
                .where(
                    m.Pattern.user_id == self.user_id,
                    m.Pattern.pattern_key == row.pattern_key,
                    m.Pattern.surfaced_at.is_not(None),
                )
                .order_by(m.Pattern.surfaced_at.desc(), m.Pattern.id.desc())
                .limit(1)
            )
            if last is None or row.effect * last.effect < 0 or rank[row.tier] > rank[last.tier]:
                row.surfaced_at = now
                self.repo.session.flush()
                return row
        return None

    def snapshot(self, pattern_id: UUID) -> dict[str, JsonValue]:
        row = self.repo.session.scalar(
            select(m.Pattern).where(
                m.Pattern.user_id == self.user_id,
                m.Pattern.id == pattern_id,
                m.Pattern.surfaced_at.is_not(None),
            )
        )
        if row is None:
            raise ValueError("Surfaced insight not found")
        return deepcopy(
            JSON.validate_python(PatternRecord.model_validate(row).model_dump(mode="json"))
        )

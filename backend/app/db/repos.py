"""Validated, user-scoped persistence; caller owns the transaction and commit."""

from datetime import date, datetime
from typing import TypeVar
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import JsonValue, TypeAdapter
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.db import models as m
from app.domain.normalize import normalize
from app.domain.schemas import (
    Direction,
    EventInput,
    ExposureTracking,
    MessageInput,
    OutcomeTracking,
    PendingState,
    RatingInput,
    TrackingState,
    UserInput,
)

T = TypeVar("T", bound=m.Base)
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _save(self, row: T) -> T:
        self.session.add(row)
        self.session.flush()
        return row

    def _user(self, user_id: UUID, *, lock: bool = False) -> m.User:
        query = select(m.User).where(m.User.id == user_id)
        if lock:
            query = query.with_for_update()
        user = self.session.scalar(query)
        if user is None:
            raise ValueError("User not found")
        return user

    def create_user(self, data: UserInput, *, user_id: UUID | None = None) -> m.User:
        row = m.User(**data.model_dump())
        if user_id is not None:
            row.id = user_id
        return self._save(row)

    def get_user(self, user_id: UUID) -> m.User | None:
        return self.session.get(m.User, user_id)

    def delete_user(self, user_id: UUID) -> bool:
        deleted = self.session.scalar(
            delete(m.User).where(m.User.id == user_id).returning(m.User.id)
        )
        # Cascades happen in the database. Expire cached child rows as well.
        self.session.expire_all()
        return deleted is not None

    def add_message(self, user_id: UUID, data: MessageInput) -> m.Message:
        self._user(user_id)
        return self._save(m.Message(user_id=user_id, **data.model_dump()))

    def find_message(self, user_id: UUID, client_msg_id: UUID) -> m.Message | None:
        return self.session.scalar(
            select(m.Message).where(
                m.Message.user_id == user_id, m.Message.client_msg_id == client_msg_id
            )
        )

    def list_messages(self, user_id: UUID, *, limit: int = 50) -> list[m.Message]:
        if not 1 <= limit <= 200:
            raise ValueError("Message limit must be between 1 and 200")
        rows = list(
            self.session.scalars(
                select(m.Message)
                .where(m.Message.user_id == user_id)
                .order_by(m.Message.created_at.desc(), m.Message.id.desc())
                .limit(limit)
            )
        )
        return list(reversed(rows))

    def get_state(self, user_id: UUID) -> PendingState:
        row = self.session.get(m.ConversationState, user_id)
        if row is None:
            return PendingState()
        return PendingState.model_validate(
            {"pending": row.pending, "last_was_clarification": row.last_was_clarification}
        )

    def save_state(self, user_id: UUID, state: PendingState) -> m.ConversationState:
        self._user(user_id)
        pending = (
            JSON_OBJECT.validate_python(state.pending.model_dump(mode="json"))
            if state.pending
            else None
        )
        statement = (
            insert(m.ConversationState)
            .values(
                user_id=user_id,
                pending=pending,
                last_was_clarification=state.last_was_clarification,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "pending": pending,
                    "last_was_clarification": state.last_was_clarification,
                    "updated_at": func.clock_timestamp(),
                },
            )
            .returning(m.ConversationState)
        )
        return self.session.scalars(statement, execution_options={"populate_existing": True}).one()

    def get_tracking(self, user_id: UUID) -> TrackingState:
        user = self._user(user_id)
        outcomes = self.session.scalars(
            select(m.TrackedOutcome)
            .where(m.TrackedOutcome.user_id == user_id, m.TrackedOutcome.active)
            .order_by(m.TrackedOutcome.name)
        )
        exposures = self.session.scalars(
            select(m.TrackedExposure)
            .where(
                m.TrackedExposure.user_id == user_id,
                m.TrackedExposure.active,
                m.TrackedExposure.declined.is_(False),
            )
            .order_by(m.TrackedExposure.name)
        )
        return TrackingState(
            outcomes=[OutcomeTracking.model_validate(row) for row in outcomes],
            exposures=[ExposureTracking.model_validate(row) for row in exposures],
            track_sleep=user.track_sleep,
        )

    def set_tracking(
        self,
        user_id: UUID,
        *,
        outcomes: list[tuple[str, Direction]] | None = None,
        exposures: list[str] | None = None,
        track_sleep: bool | None = None,
    ) -> TrackingState:
        user = self._user(user_id, lock=True)
        existing = self.get_tracking(user_id)
        new_outcomes = (
            [
                OutcomeTracking(name=normalize(name).canonical, direction_better=direction)
                for name, direction in outcomes
            ]
            if outcomes is not None
            else existing.outcomes
        )
        new_exposures = (
            [ExposureTracking(name=normalize(name).canonical) for name in exposures]
            if exposures is not None
            else existing.exposures
        )
        target = TrackingState(
            outcomes=new_outcomes,
            exposures=new_exposures,
            track_sleep=track_sleep if track_sleep is not None else user.track_sleep,
        )
        if len({row.name for row in target.outcomes}) != len(target.outcomes):
            raise ValueError("Duplicate tracked outcome")
        if len({row.name for row in target.exposures}) != len(target.exposures):
            raise ValueError("Duplicate tracked exposure")
        if outcomes is not None:
            self._replace_outcomes(user_id, target.outcomes)
        if exposures is not None:
            self._replace_exposures(user_id, target.exposures)
        user.track_sleep = target.track_sleep
        self.session.flush()
        return target

    def _replace_outcomes(self, user_id: UUID, items: list[OutcomeTracking]) -> None:
        rows = {
            row.name: row
            for row in self.session.scalars(
                select(m.TrackedOutcome).where(m.TrackedOutcome.user_id == user_id)
            )
        }
        for row in rows.values():
            row.active = False
        for item in items:
            if item.name in rows:
                rows[item.name].active = True
                rows[item.name].direction_better = item.direction_better
            else:
                self.session.add(m.TrackedOutcome(user_id=user_id, **item.model_dump()))

    def _replace_exposures(self, user_id: UUID, items: list[ExposureTracking]) -> None:
        rows = {
            row.name: row
            for row in self.session.scalars(
                select(m.TrackedExposure).where(m.TrackedExposure.user_id == user_id)
            )
        }
        for row in rows.values():
            row.active = False
        for item in items:
            if item.name in rows:
                rows[item.name].active = True
                rows[item.name].declined = False
            else:
                self.session.add(m.TrackedExposure(user_id=user_id, **item.model_dump()))

    def upsert_checkin(
        self,
        user_id: UUID,
        local_date: date,
        *,
        completed: bool | None = None,
        checklist_answered: bool | None = None,
    ) -> m.Checkin:
        self._user(user_id)
        statement = insert(m.Checkin).values(
            user_id=user_id,
            local_date=local_date,
            completed=completed if completed is not None else False,
            checklist_answered=checklist_answered if checklist_answered is not None else False,
        )
        changes: dict[str, bool] = {}
        if completed is not None:
            changes["completed"] = completed
        if checklist_answered is not None:
            changes["checklist_answered"] = checklist_answered
        # A no-op assignment preserves the existing flags if no update is requested.
        upsert = statement.on_conflict_do_update(
            index_elements=["user_id", "local_date"],
            set_=changes or {"local_date": statement.excluded.local_date},
        ).returning(m.Checkin)
        return self.session.scalars(upsert, execution_options={"populate_existing": True}).one()

    def upsert_rating(
        self, user_id: UUID, local_date: date, outcome_name: str, value: int
    ) -> m.OutcomeRating:
        self._user(user_id)
        data = RatingInput(
            local_date=local_date, outcome_name=normalize(outcome_name).canonical, value=value
        )
        statement = (
            insert(m.OutcomeRating)
            .values(user_id=user_id, **data.model_dump())
            .on_conflict_do_update(
                index_elements=["user_id", "local_date", "outcome_name"],
                set_={"value": value, "updated_at": func.clock_timestamp()},
            )
            .returning(m.OutcomeRating)
        )
        return self.session.scalars(statement, execution_options={"populate_existing": True}).one()

    def list_ratings(self, user_id: UUID, start: date, end: date) -> list[m.OutcomeRating]:
        return list(
            self.session.scalars(
                select(m.OutcomeRating)
                .where(
                    m.OutcomeRating.user_id == user_id,
                    m.OutcomeRating.local_date.between(start, end),
                )
                .order_by(m.OutcomeRating.local_date, m.OutcomeRating.outcome_name)
            )
        )

    def add_event(
        self,
        user_id: UUID,
        data: EventInput,
        *,
        ts: datetime,
        local_date: date,
        message_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> m.Event:
        user = self._user(user_id)
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError("Event timestamp must be timezone-aware")
        if created_at is not None and (created_at.tzinfo is None or created_at.utcoffset() is None):
            raise ValueError("Event creation timestamp must be timezone-aware")
        if ts.astimezone(ZoneInfo(user.tz)).date() != local_date:
            raise ValueError("Event timestamp does not match its local date")
        if message_id is not None:
            message = self.session.get(m.Message, message_id)
            if message is None or message.user_id != user_id:
                raise ValueError("Event message does not belong to this user")
        name = normalize(data.name)
        row = m.Event(
            user_id=user_id,
            message_id=message_id,
            ts=ts,
            local_date=local_date,
            **data.model_dump(exclude={"name", "raw_name"}),
            name=name.canonical,
            raw_name=data.raw_name if data.raw_name is not None else data.name,
        )
        if created_at is not None:
            row.created_at = created_at
        return self._save(row)

    def list_events(self, user_id: UUID, start: date, end: date) -> list[m.Event]:
        return list(
            self.session.scalars(
                select(m.Event)
                .where(m.Event.user_id == user_id, m.Event.local_date.between(start, end))
                .order_by(m.Event.created_at, m.Event.id)
            )
        )

    def latest_events(self, user_id: UUID, start: date, end: date) -> list[m.Event]:
        ranked = (
            select(
                m.Event,
                func.row_number()
                .over(
                    partition_by=(m.Event.local_date, m.Event.name),
                    order_by=(m.Event.created_at.desc(), m.Event.id.desc()),
                )
                .label("position"),
            )
            .where(m.Event.user_id == user_id, m.Event.local_date.between(start, end))
            .subquery()
        )
        event = aliased(m.Event, ranked)
        return list(
            self.session.scalars(
                select(event).where(ranked.c.position == 1).order_by(event.local_date, event.name)
            )
        )

    def add_experiment(
        self,
        user_id: UUID,
        *,
        exposure: str,
        outcome: str,
        protocol: dict[str, JsonValue],
        seed: int,
        pattern_id: UUID | None = None,
    ) -> m.Experiment:
        self._user(user_id)
        if pattern_id is not None:
            pattern = self.session.get(m.Pattern, pattern_id)
            if pattern is None or pattern.user_id != user_id:
                raise ValueError("Experiment pattern does not belong to this user")
        return self._save(
            m.Experiment(
                user_id=user_id,
                exposure=normalize(exposure).canonical,
                outcome=normalize(outcome).canonical,
                protocol=protocol,
                seed=seed,
                pattern_id=pattern_id,
            )
        )

"""Content-free attempt ledger. SQL transactions serialize budget reservations."""

from collections.abc import Collection, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ConfigDict
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.db.models import LLMCall, User
from app.domain.schemas import LLMCallInput


@dataclass(frozen=True)
class UserIdentity:
    id: UUID
    data_class: Literal["real", "synthetic"]
    tz: str
    is_demo: bool


class CallTrace(LLMCallInput):
    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)
    id: UUID
    created_at: datetime


class TraceTransaction(Protocol):
    def user(self, user_id: UUID) -> UserIdentity | None: ...
    def records(
        self, *, since: datetime | None = None, ids: Collection[UUID] | None = None
    ) -> list[CallTrace]: ...
    def put(self, row: CallTrace) -> None: ...


class TraceStore(Protocol):
    def transaction(self) -> AbstractContextManager[TraceTransaction]: ...


class MemoryTraceStore:
    """Explicit offline test store; production uses SQLTraceStore."""

    def __init__(self, *, users: Collection[UserIdentity] = ()) -> None:
        self._users = {user.id: user for user in users}
        self._rows: dict[UUID, CallTrace] = {}
        self._lock = RLock()

    @property
    def rows(self) -> list[CallTrace]:
        return list(self._rows.values())

    @contextmanager
    def transaction(self) -> Iterator[TraceTransaction]:
        with self._lock:
            yield self

    def user(self, user_id: UUID) -> UserIdentity | None:
        return self._users.get(user_id)

    def records(
        self, *, since: datetime | None = None, ids: Collection[UUID] | None = None
    ) -> list[CallTrace]:
        return [
            row
            for row in self.rows
            if (since is None or row.created_at >= since) and (ids is None or row.id in ids)
        ]

    def put(self, row: CallTrace) -> None:
        self._rows[row.id] = row


class SQLTraceTransaction:
    def __init__(self, session: Session) -> None:
        self.session = session

    def user(self, user_id: UUID) -> UserIdentity | None:
        user = self.session.get(User, user_id)
        if user is None:
            return None
        return UserIdentity(
            user.id,
            "synthetic" if user.data_class == "synthetic" else "real",
            user.tz,
            user.is_demo,
        )

    def records(
        self, *, since: datetime | None = None, ids: Collection[UUID] | None = None
    ) -> list[CallTrace]:
        query = select(LLMCall).order_by(
            LLMCall.created_at, LLMCall.trace_id, LLMCall.purpose, LLMCall.attempt, LLMCall.id
        )
        if since is not None:
            query = query.where(LLMCall.created_at >= since)
        if ids is not None:
            query = query.where(LLMCall.id.in_(ids))
        return [CallTrace.model_validate(row) for row in self.session.scalars(query)]

    def put(self, row: CallTrace) -> None:
        self.session.merge(LLMCall(**row.model_dump()))
        self.session.flush()


class SQLTraceStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[TraceTransaction]:
        with Session(self.engine) as session, session.begin():
            # One project-local lock serializes all workers' global/day reservations.
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 741904})
            yield SQLTraceTransaction(session)

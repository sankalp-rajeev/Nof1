"""Turn-local persistence evidence read back from successful database mutations."""

from datetime import date, timedelta
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select

from app.db import models as m
from app.db.repos import Repository


class PersistenceReceipts:
    def __init__(self, repo: Repository, user_id: UUID, message_id: UUID, day: date) -> None:
        self.repo, self.user_id, self.message_id, self.day = repo, user_id, message_id, day
        self.before = {row.id: row.updated_at for row in self._ratings()}

    def _ratings(self) -> list[m.OutcomeRating]:
        return self.repo.list_ratings(self.user_id, self.day - timedelta(days=6), self.day)

    def payload(self) -> dict[str, JsonValue]:
        self.repo.session.flush()
        events = self.repo.session.scalars(
            select(m.Event)
            .where(m.Event.user_id == self.user_id, m.Event.message_id == self.message_id)
            .order_by(m.Event.created_at, m.Event.id)
        )
        event_values: list[JsonValue] = [
            {
                "name": row.name,
                "kind": row.kind,
                "status": row.status,
                "date": row.local_date.isoformat(),
                "value": row.value,
                "severity": row.severity,
            }
            for row in events
        ]
        rating_values: list[JsonValue] = [
            {"name": row.outcome_name, "value": row.value, "date": row.local_date.isoformat()}
            for row in self._ratings()
            if self.before.get(row.id) != row.updated_at
        ]
        return {"events_logged": event_values, "ratings_recorded": rating_values}

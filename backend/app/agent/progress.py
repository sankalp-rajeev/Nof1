"""Small server-owned workflow state; reset daily skips without losing onboarding."""

from datetime import date as LocalDate
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models import ConversationState
from app.db.repos import Repository
from app.domain.schemas import DomainModel, PendingState


class Progress(DomainModel):
    date: LocalDate | None = None
    onboarding: Literal["outcomes", "exposures", "sleep", "done"] | None = None
    skipped_outcomes: list[str] = Field(default_factory=list)
    sleep_skipped: bool = False
    checklist_skipped: bool = False
    suggested_on: LocalDate | None = None


def load_progress(repo: Repository, user_id: UUID, day: LocalDate) -> tuple[Progress, PendingState]:
    row = repo.session.get(ConversationState, user_id)
    progress = Progress.model_validate(row.progress if row else {})
    state = repo.get_state(user_id)
    if progress.onboarding is None:
        progress.onboarding = "done" if repo.get_tracking(user_id).outcomes else "outcomes"
    if progress.date != day:
        progress.date = day
        progress.skipped_outcomes = []
        progress.sleep_skipped = progress.checklist_skipped = False
        if state.pending and state.pending.type in {
            "rate_outcome",
            "sleep_hours",
            "exposure_checklist",
            "experiment_adherence",
        }:
            state.pending = None
    return progress, state


def save_progress(repo: Repository, user_id: UUID, progress: Progress, state: PendingState) -> None:
    row = repo.save_state(user_id, state)
    row.progress = progress.model_dump(mode="json")
    repo.session.flush()

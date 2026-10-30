"""Section 6 application tables with constraints enforced by PostgreSQL."""

from datetime import date, datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Identity:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Created:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class Updated:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
    )


class UserOwned:
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class User(Identity, Created, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("data_class IN ('real','synthetic')", name="data_class"),
        CheckConstraint("is_demo OR clock_offset_days = 0", name="demo_clock"),
    )
    tz: Mapped[str] = mapped_column(server_default="UTC")
    is_demo: Mapped[bool] = mapped_column(server_default=text("false"))
    data_class: Mapped[str] = mapped_column(server_default="real")
    track_sleep: Mapped[bool] = mapped_column(server_default=text("false"))
    clock_offset_days: Mapped[int] = mapped_column(server_default="0")


class Message(Identity, Created, UserOwned, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("user_id", "client_msg_id"),
        CheckConstraint("role IN ('user','assistant')", name="role"),
    )
    role: Mapped[str]
    content: Mapped[str]
    client_msg_id: Mapped[UUID | None]
    trace_id: Mapped[UUID]


class ConversationState(Updated, Base):
    __tablename__ = "conversation_state"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pending: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))
    last_was_clarification: Mapped[bool] = mapped_column(server_default=text("false"))


class TrackedOutcome(Identity, Created, UserOwned, Base):
    __tablename__ = "tracked_outcomes"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        CheckConstraint("direction_better IN ('lower','higher')", name="direction"),
    )
    name: Mapped[str]
    direction_better: Mapped[str] = mapped_column(server_default="lower")
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class TrackedExposure(Identity, Created, UserOwned, Base):
    __tablename__ = "tracked_exposures"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    name: Mapped[str]
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    declined: Mapped[bool] = mapped_column(server_default=text("false"))


class Checkin(Identity, Created, UserOwned, Base):
    __tablename__ = "checkins"
    __table_args__ = (UniqueConstraint("user_id", "local_date"),)
    local_date: Mapped[date]
    completed: Mapped[bool] = mapped_column(server_default=text("false"))
    checklist_answered: Mapped[bool] = mapped_column(server_default=text("false"))


class Event(Identity, Created, UserOwned, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("kind IN ('meal','med','symptom','sleep','life')", name="kind"),
        CheckConstraint("status IN ('done','skipped')", name="status"),
        CheckConstraint("source IN ('chat','checklist','demo','sim')", name="source"),
        CheckConstraint(
            "severity IS NULL OR (kind = 'symptom' AND severity BETWEEN 0 AND 10)", name="severity"
        ),
        CheckConstraint("status <> 'skipped' OR kind NOT IN ('symptom','sleep')", name="skipped"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
        Index("ix_events_latest", "user_id", "local_date", "name", "created_at", "id"),
    )
    message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date]
    kind: Mapped[str]
    name: Mapped[str]
    raw_name: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="done")
    source: Mapped[str] = mapped_column(server_default="chat")
    value: Mapped[float | None]
    unit: Mapped[str | None]
    severity: Mapped[int | None]
    confidence: Mapped[float] = mapped_column(server_default="1")


class OutcomeRating(Identity, Updated, UserOwned, Base):
    __tablename__ = "outcome_ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", "outcome_name"),
        CheckConstraint("value BETWEEN 0 AND 10", name="value"),
    )
    local_date: Mapped[date]
    outcome_name: Mapped[str]
    value: Mapped[int]


class Pattern(Identity, UserOwned, Base):
    __tablename__ = "patterns"
    __table_args__ = (
        CheckConstraint("tier IN ('weak','moderate')", name="tier"),
        CheckConstraint("lag_days BETWEEN 0 AND 2", name="lag"),
        CheckConstraint("p_raw BETWEEN 0 AND 1 AND p_adj BETWEEN 0 AND 1", name="probabilities"),
        CheckConstraint("n_pairs >= 0 AND n_exposed >= 0 AND n_unexposed >= 0", name="counts"),
        CheckConstraint("window_start <= window_end", name="window"),
    )
    run_id: Mapped[UUID]
    pattern_key: Mapped[str]
    exposure: Mapped[str]
    outcome: Mapped[str]
    lag_days: Mapped[int]
    effect: Mapped[float]
    p_raw: Mapped[float]
    p_adj: Mapped[float]
    tier: Mapped[str]
    n_pairs: Mapped[int]
    n_exposed: Mapped[int]
    n_unexposed: Mapped[int]
    confounder: Mapped[str | None]
    window_start: Mapped[date]
    window_end: Mapped[date]
    data_points: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    surfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class Experiment(Identity, Created, UserOwned, Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','accepted','baseline','running','completed','abandoned')",
            name="status",
        ),
        CheckConstraint("end_reason IN ('expired','user')", name="end_reason"),
        Index(
            "uq_experiments_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('proposed','accepted','baseline','running')"),
        ),
    )
    pattern_id: Mapped[UUID | None] = mapped_column(ForeignKey("patterns.id", ondelete="SET NULL"))
    exposure: Mapped[str]
    outcome: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="proposed")
    end_reason: Mapped[str | None]
    protocol: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    seed: Mapped[int]
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_on: Mapped[date | None]
    ended_on: Mapped[date | None]
    verdict: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB(none_as_null=True))


class ExperimentDay(Identity, Updated, Base):
    __tablename__ = "experiment_days"
    __table_args__ = (
        UniqueConstraint("experiment_id", "date"),
        CheckConstraint("phase IN ('baseline','on','off')", name="phase"),
    )
    experiment_id: Mapped[UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date]
    phase: Mapped[str]
    washout: Mapped[bool] = mapped_column(server_default=text("false"))
    adherence: Mapped[bool | None]


class LLMCall(Identity, Created, Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint("data_class IN ('real','synthetic')", name="data_class"),
        CheckConstraint("status IN ('ok','error','invalid','budget')", name="status"),
        CheckConstraint(
            "attempt >= 1 AND input_tokens >= 0 AND output_tokens >= 0 AND latency_ms >= 0",
            name="usage",
        ),
        CheckConstraint("cost_usd IS NULL OR cost_usd >= 0", name="cost"),
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    trace_id: Mapped[UUID]
    purpose: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str]
    prompt_version: Mapped[int]
    data_class: Mapped[str]
    attempt: Mapped[int]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    latency_ms: Mapped[float]
    cost_usd: Mapped[float | None]
    status: Mapped[str]
    error: Mapped[str | None]


class SafetyEvent(Identity, Created, UserOwned, Base):
    __tablename__ = "safety_events"
    __table_args__ = (CheckConstraint("source IN ('rule','llm')", name="source"),)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    category: Mapped[str]
    source: Mapped[str]

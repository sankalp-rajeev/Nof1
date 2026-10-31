"""Boundary schemas. Validation never executes instructions from user text."""

from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.config import MAX_TRACKED_EXPOSURES, MAX_TRACKED_OUTCOMES, RATING_MAX, RATING_MIN

Kind = Literal["meal", "med", "symptom", "sleep", "life"]
Category = Literal["supplement", "otc_med", "rx_med", "food", "habit", "symptom"]
Direction = Literal["lower", "higher"]
DataClass = Literal["real", "synthetic"]
Phase = Literal["baseline", "on", "off"]
ExperimentStatus = Literal["proposed", "accepted", "baseline", "running", "completed", "abandoned"]
Name = Annotated[str, Field(min_length=1)]
Rating = Annotated[int, Field(ge=RATING_MIN, le=RATING_MAX, strict=True)]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)


class UserInput(DomainModel):
    tz: str = "UTC"
    is_demo: bool = False
    data_class: DataClass = "real"
    track_sleep: bool = False
    clock_offset_days: int = 0

    @field_validator("tz")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def demo_clock_only(self) -> Self:
        if self.clock_offset_days and not self.is_demo:
            raise ValueError("A clock offset is allowed only for demo users")
        return self


class UserRecord(UserInput):
    id: UUID
    created_at: datetime


class MessageInput(DomainModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(strip_whitespace=False, min_length=1)]
    trace_id: UUID
    client_msg_id: UUID | None = None


class MessageRecord(MessageInput):
    id: UUID
    user_id: UUID
    created_at: datetime


class EventInput(DomainModel):
    kind: Kind
    name: Name
    raw_name: Annotated[str, StringConstraints(strip_whitespace=False)] | None = None
    status: Literal["done", "skipped"] = "done"
    source: Literal["chat", "checklist", "demo", "sim"] = "chat"
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = None
    severity: Rating | None = None
    confidence: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_event(self) -> Self:
        if self.severity is not None and self.kind != "symptom":
            raise ValueError("severity is allowed only on symptoms")
        if self.status == "skipped" and self.kind in {"symptom", "sleep"}:
            raise ValueError("skipped is not allowed for symptom or sleep")
        return self


class EventRecord(EventInput):
    id: UUID
    user_id: UUID
    message_id: UUID | None
    ts: datetime
    local_date: date
    created_at: datetime


class OutcomeTracking(DomainModel):
    name: Name
    direction_better: Direction = "lower"
    active: bool = True


class ExposureTracking(DomainModel):
    name: Name
    active: bool = True
    declined: bool = False


class TrackingState(DomainModel):
    outcomes: list[OutcomeTracking] = Field(default_factory=list, max_length=MAX_TRACKED_OUTCOMES)
    exposures: list[ExposureTracking] = Field(
        default_factory=list, max_length=MAX_TRACKED_EXPOSURES
    )
    track_sleep: bool = False


class CheckinRecord(DomainModel):
    id: UUID
    user_id: UUID
    local_date: date
    completed: bool
    checklist_answered: bool
    created_at: datetime


class RatingInput(DomainModel):
    local_date: date
    outcome_name: Name
    value: Rating


class RatingRecord(RatingInput):
    id: UUID
    user_id: UUID
    updated_at: datetime


class PatternRecord(DomainModel):
    id: UUID
    user_id: UUID
    run_id: UUID
    pattern_key: Name
    exposure: Name
    outcome: Name
    lag_days: int = Field(ge=0, le=2)
    effect: float
    p_raw: float = Field(ge=0, le=1)
    p_adj: float = Field(ge=0, le=1)
    tier: Literal["weak", "moderate"]
    n_pairs: int = Field(ge=0)
    n_exposed: int = Field(ge=0)
    n_unexposed: int = Field(ge=0)
    perm_mode: Literal["exact", "mc"] | None = None
    n_valid: int | None = Field(default=None, ge=1)
    confounder: str | None
    window_start: date
    window_end: date
    data_points: list[dict[str, JsonValue]]
    surfaced_at: datetime | None
    computed_at: datetime


class ExperimentRecord(DomainModel):
    id: UUID
    user_id: UUID
    pattern_id: UUID | None
    exposure: Name
    outcome: Name
    status: ExperimentStatus
    end_reason: Literal["expired", "user"] | None
    protocol: dict[str, JsonValue]
    seed: int
    created_at: datetime
    accepted_at: datetime | None
    started_on: date | None
    ended_on: date | None
    verdict: dict[str, JsonValue] | None


class ExperimentDayInput(DomainModel):
    date: date
    phase: Phase
    washout: bool = False
    adherence: bool | None = None


class ExperimentDayRecord(ExperimentDayInput):
    id: UUID
    experiment_id: UUID
    updated_at: datetime


class LLMCallInput(DomainModel):
    trace_id: UUID
    user_id: UUID | None = None
    purpose: Name
    provider: Name
    model: Name
    prompt_version: int = Field(ge=1)
    data_class: DataClass
    attempt: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reserved_input_tokens: int = Field(default=0, ge=0)
    reserved_output_tokens: int = Field(default=0, ge=0)
    reserved_cost_usd: float | None = Field(default=None, ge=0)
    latency_ms: float = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    status: Literal["ok", "error", "invalid", "budget"]
    error: str | None = None


class SafetyEventInput(DomainModel):
    user_id: UUID
    message_id: UUID
    category: Name
    source: Literal["rule", "llm"]


class OnboardingOutcomes(DomainModel):
    type: Literal["onboarding_outcomes"]


class OnboardingExposures(DomainModel):
    type: Literal["onboarding_exposures"]


class OnboardingSleep(DomainModel):
    type: Literal["onboarding_sleep"]


class RateOutcome(DomainModel):
    type: Literal["rate_outcome"]
    outcome: Name


class SleepHours(DomainModel):
    type: Literal["sleep_hours"]
    date: date


class ExposureChecklist(DomainModel):
    type: Literal["exposure_checklist"]
    date: date
    names: list[Name] = Field(max_length=MAX_TRACKED_EXPOSURES)


class ExperimentAdherence(DomainModel):
    type: Literal["experiment_adherence"]
    experiment_id: UUID
    date: date


class ConfirmExperiment(DomainModel):
    type: Literal["confirm_experiment"]
    experiment_id: UUID


class ConfirmTrack(DomainModel):
    type: Literal["confirm_track"]
    name: Name


Pending = Annotated[
    OnboardingOutcomes
    | OnboardingExposures
    | OnboardingSleep
    | RateOutcome
    | SleepHours
    | ExposureChecklist
    | ExperimentAdherence
    | ConfirmExperiment
    | ConfirmTrack,
    Field(discriminator="type"),
]


class PendingState(DomainModel):
    pending: Pending | None = None
    last_was_clarification: bool = False

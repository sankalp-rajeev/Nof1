"""One typed perception step; mutations are owned by deterministic application code."""

import json
import re
from typing import Literal, Self

from pydantic import Field, model_validator

from app.agent.llm.base import CallContext, LLMMessage
from app.agent.llm.router import LLMRouter
from app.agent.llm.structured import StructuredResult, generate_structured
from app.config import MAX_EVENT_NAME_LENGTH, MAX_EXTRACTED_EVENTS
from app.domain.normalize import normalize
from app.domain.schemas import Direction, DomainModel, Kind, Rating

Intent = Literal["checkin", "ask_data", "experiment", "medical_ask", "chitchat"]


class ExtractedEvent(DomainModel):
    kind: Kind
    name: str = Field(min_length=1, max_length=MAX_EVENT_NAME_LENGTH)
    status: Literal["done", "skipped"] = "done"
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = None
    severity: Rating | None = None
    relative_day: int = Field(default=0, ge=-6, le=0)
    time_of_day: Literal["morning", "afternoon", "evening", "night", "unspecified"] = "unspecified"

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.severity is not None and self.kind != "symptom":
            raise ValueError("Only symptoms have severity")
        if self.kind in {"symptom", "sleep"} and self.status == "skipped":
            raise ValueError("Skipped is limited to exposures")
        if self.kind == "sleep" and self.value is not None and not 0 <= self.value <= 16:
            raise ValueError("Sleep hours must be between 0 and 16")
        return self


class RatingUpdate(DomainModel):
    outcome: str = Field(min_length=1, max_length=MAX_EVENT_NAME_LENGTH)
    value: Rating
    relative_day: int = Field(default=0, ge=-6, le=0)


class OutcomeSetup(DomainModel):
    name: str = Field(min_length=1, max_length=MAX_EVENT_NAME_LENGTH)
    direction_better: Direction = "lower"


class TurnAnalysis(DomainModel):
    intent: Intent
    events: list[ExtractedEvent] = Field(default_factory=list, max_length=MAX_EXTRACTED_EVENTS)
    ratings: list[RatingUpdate] = Field(default_factory=list, max_length=MAX_EXTRACTED_EVENTS)
    setup_outcomes: list[OutcomeSetup] = Field(default_factory=list, max_length=3)
    setup_exposures: list[str] = Field(default_factory=list, max_length=5)
    setup_sleep: bool | None = None
    checklist_yes: list[str] = Field(default_factory=list, max_length=MAX_EXTRACTED_EVENTS)
    checklist_none: bool = False
    adherence: bool | None = None
    experiment_action: Literal["start", "accept", "abandon"] | None = None
    experiment_target: str | None = None
    skip: bool = False
    clarification_question: str | None = None
    possible_emergency: bool = False


def analyze(
    router: LLMRouter, messages: tuple[LLMMessage, ...], *, ctx: CallContext
) -> StructuredResult[TurnAnalysis]:
    payload = json.loads(
        next(message.content for message in reversed(messages) if message.role == "user")
    )
    current = str(payload.get("user_text", ""))
    tracking = payload.get("tracking", {})
    tracked = {normalize(row["name"]).canonical for row in tracking.get("outcomes", [])}
    reported_numbers = {
        float(value) for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", current)
    }

    def grounded(value: TurnAnalysis) -> None:
        if any(
            r.value not in reported_numbers
            for r in value.ratings
            if normalize(r.outcome).canonical in tracked
        ):
            raise ValueError("Ratings require explicit numeric evidence in the current message")
        if any(e.severity is not None and e.severity not in reported_numbers for e in value.events):
            raise ValueError("Severity requires explicit numeric evidence in the current message")

    return generate_structured(
        router,
        messages,
        schema=TurnAnalysis,
        ctx=ctx,
        max_tokens=router.settings.max_output_tokens,
        validate=grounded,
    )

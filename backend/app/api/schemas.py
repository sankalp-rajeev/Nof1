from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from app.domain.schemas import DomainModel, Rating


class ChatInput(DomainModel):
    message: str = Field(min_length=1, max_length=20000)
    tz: str = "UTC"
    client_msg_id: UUID | None = None

    @field_validator("tz")
    @classmethod
    def timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        return value


class ProposalInput(DomainModel):
    pattern_id: UUID | None = None
    exposure: str | None = None
    outcome: str | None = None

    @model_validator(mode="after")
    def target(self) -> "ProposalInput":
        if not self.pattern_id and not self.exposure:
            raise ValueError("A pattern or exposure is required")
        if self.pattern_id and (self.exposure or self.outcome):
            raise ValueError("Choose a pattern or explicit target")
        return self


class DayInput(DomainModel):
    adherence: bool = Field(strict=True)
    outcome_value: Rating | None = None


class AdvanceInput(DomainModel):
    days: int = Field(ge=1, le=14, strict=True)

"""Provider-independent contracts. Implementations must receive per-call context."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel


@dataclass(frozen=True)
class CallContext:
    purpose: str
    data_class: Literal["real", "synthetic"]
    user_id: UUID | None
    trace_id: UUID


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    call_id: UUID | None = None


class PolicyError(RuntimeError):
    """The per-call data policy rejected an attempt before provider access."""


class ProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        route: str | None = None,
        exception_class: str = "ProviderError",
        google_status: str | None = None,
        provider_message: str | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.exception_class = exception_class
        self.google_status = google_status
        self.provider_message = provider_message
        super().__init__(code if route is None else f"{code}: {route}")


class LLMClient(Protocol):
    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        """Return provider text and usage; structured output is validated by the caller."""
        ...

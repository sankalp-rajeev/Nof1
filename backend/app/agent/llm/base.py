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

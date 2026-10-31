"""Two attempts total for schema validation; failures return a defined empty result."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.agent.llm.base import CallContext, LLMMessage
from app.agent.llm.router import LLMRouter

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    value: T | None
    attempts: int


def generate_structured(
    router: LLMRouter,
    messages: Sequence[LLMMessage],
    *,
    schema: type[T],
    ctx: CallContext,
    max_tokens: int,
) -> StructuredResult[T]:
    pending = list(messages)
    for attempt in range(2):
        response = router.get(ctx.purpose).generate(
            pending, schema=schema, max_tokens=max_tokens, temperature=0, ctx=ctx
        )
        try:
            return StructuredResult(schema.model_validate_json(response.text), attempt + 1)
        except ValidationError:
            router.mark_invalid(response)
            pending.append(LLMMessage("system", "Return valid JSON matching the supplied schema."))
    return StructuredResult(None, 2)

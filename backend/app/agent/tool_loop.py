"""Bounded read-only choices; model proposals never receive mutation dispatch rights."""

from copy import deepcopy
from dataclasses import dataclass

from pydantic import Field, JsonValue

from app.agent.context import Context, ContextBuilder
from app.agent.llm.base import CallContext
from app.agent.llm.router import LLMRouter
from app.agent.llm.structured import generate_structured
from app.agent.tools.registry import ToolRegistry
from app.config import PATH_CONTEXT_TOKENS, TOOL_CALL_LIMIT
from app.domain.schemas import DomainModel


class ToolChoice(DomainModel):
    tool: str | None = None
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class LoopResult:
    results: list[dict[str, JsonValue]]
    calls: int


def run_readonly_loop(
    router: LLMRouter, tools: ToolRegistry, context: Context, ctx: CallContext
) -> LoopResult:
    payload = deepcopy(context.payload)
    payload.pop("history", None)
    descriptions: list[JsonValue] = []
    descriptions.extend(tools.descriptions())
    payload["tools"] = descriptions
    results: list[dict[str, JsonValue]] = []
    errors = 0
    for _ in range(TOOL_CALL_LIMIT):
        fitted = ContextBuilder._fit(
            payload, "composer_answer", PATH_CONTEXT_TOKENS, facts_only=True
        )
        decision = generate_structured(
            router,
            fitted.messages,
            schema=ToolChoice,
            ctx=ctx,
            max_tokens=router.settings.max_output_tokens,
        ).value
        if decision is None or decision.tool is None:
            break
        result = tools.execute(decision.tool, decision.arguments)
        results.append(result)
        if "error" in result:
            errors += 1
            if errors > 1:
                break
        values: list[JsonValue] = []
        values.extend(results)
        payload["tool_results"] = values
    values = []
    values.extend(results)
    payload["tool_results"] = values
    fitted = ContextBuilder._fit(payload, "composer_answer", PATH_CONTEXT_TOKENS, facts_only=True)
    compact = fitted.payload["tool_results"]
    assert isinstance(compact, list)
    return LoopResult([row for row in compact if isinstance(row, dict)], len(results))

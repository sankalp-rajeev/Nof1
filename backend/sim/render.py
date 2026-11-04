"""Bounded persona phrasing. Only code-selected observations cross the LLM boundary."""

import re
from dataclasses import dataclass

from pydantic import Field, ValidationError

from app.agent.llm.base import CallContext, LLMMessage, ProviderError
from app.agent.llm.cost import BudgetExceeded
from app.agent.llm.router import LLMRouter
from app.agent.prompts.loader import load_prompt
from app.domain.normalize import load_aliases, normalize
from app.domain.schemas import DomainModel
from sim.config import RENDER_ATTEMPTS, RENDER_MAX_CHARS
from sim.extraction import Label
from sim.personas import Persona

BANNED = re.compile(r"\b(?:because|caus(?:e[ds]?|ing)|patterns?|effects?)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?!\w|\.\d)")
NEGATION = re.compile(r"\b(?:skip(?:ped)?|no|not|didn't|didnt|without|never)\b", re.I)


class RenderedText(DomainModel):
    text: str = Field(min_length=1, max_length=RENDER_MAX_CHARS)


@dataclass(frozen=True)
class RenderResult:
    text: str
    attempts: int
    fallback: bool


def aliases(event: Label) -> set[str]:
    name = normalize(event.name).canonical
    return {name} | {a.alias.casefold() for a in load_aliases() if a.canonical == name}


def contains(text: str, names: set[str]) -> bool:
    return any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I) for name in names)


def validate_render(text: str, events: tuple[Label, ...]) -> tuple[str, ...]:
    failures: set[str] = set()
    if not 1 <= len(text) <= RENDER_MAX_CHARS:
        failures.add("length")
    if BANNED.search(text):
        failures.add("causal-language")
    expected_numbers = {
        float(value)
        for event in events
        for value in (event.value, event.severity)
        if value is not None
    }
    actual_numbers = {float(value) for value in NUMBER.findall(text)}
    if actual_numbers != expected_numbers:
        failures.add("numbers")
    clauses = re.split(r"[,;\n!]|\.(?!\d)|\band\b", text.casefold())
    for event in events:
        matching = [clause for clause in clauses if contains(clause, aliases(event))]
        if not matching:
            failures.add("required-name")
        elif event.kind not in {"sleep", "symptom"}:
            if not any(
                bool(NEGATION.search(clause)) == (event.status == "skipped") for clause in matching
            ):
                failures.add("status")
        if event.value is not None or event.severity is not None:
            value = event.value if event.value is not None else event.severity
            assert value is not None
            if not any(
                float(value) in {float(n) for n in NUMBER.findall(clause)} for clause in matching
            ):
                failures.add("number-binding")
    expected_names = {normalize(event.name).canonical for event in events}
    for alias in load_aliases():
        if alias.canonical not in expected_names and contains(text, {alias.alias.casefold()}):
            failures.add("unplanned-event")
    return tuple(sorted(failures))


def template(events: tuple[Label, ...]) -> str:
    if not events:
        return "Nothing to add today."
    parts = []
    for event in events:
        if event.kind == "symptom":
            parts.append(
                f"{event.name} {event.severity}" if event.severity is not None else event.name
            )
        elif event.kind == "sleep":
            parts.append(
                f"{event.name} {event.value:g} hours" if event.value is not None else event.name
            )
        else:
            parts.append(("skipped " if event.status == "skipped" else "had ") + event.name)
    return "; ".join(parts) + "."


def render(
    router: LLMRouter,
    events: tuple[Label, ...],
    persona: Persona,
    *,
    ctx: CallContext,
) -> RenderResult:
    if ctx.data_class != "synthetic":
        raise ValueError("Persona rendering is synthetic-only")
    messages = list(
        load_prompt("persona_render").messages(
            {
                "events": [e.model_dump(mode="json") for e in events],
                "persona": persona.model_dump(mode="json"),
            }
        )
    )
    for attempt in range(1, RENDER_ATTEMPTS + 1):
        try:
            response = router.get("persona").generate(
                messages,
                schema=RenderedText,
                max_tokens=router.settings.max_output_tokens,
                temperature=0,
                ctx=ctx,
            )
        except BudgetExceeded:
            raise  # Do not silently complete a live cohort using budget fallbacks.
        except ProviderError:
            raise  # A broken provider/model is not a renderer-validation fallback.
        try:
            text = RenderedText.model_validate_json(response.text).text
            failures = validate_render(text, events)
        except ValidationError:
            text, failures = "", ("schema",)
        if not failures:
            return RenderResult(text, attempt, False)
        router.mark_invalid(response, reason="render:" + ",".join(failures))
        messages.append(
            LLMMessage("system", "Render the same events again; validation: " + ",".join(failures))
        )
    return RenderResult(template(events), RENDER_ATTEMPTS, True)

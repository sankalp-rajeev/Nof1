"""Facts-only acknowledgement/answer; code owns the next question and final guard."""

from dataclasses import dataclass

from pydantic import JsonValue

from app.agent.llm.base import CallContext
from app.agent.llm.router import LLMRouter
from app.agent.pending import question_text
from app.agent.safety.output_guard import Facts, OutputGuard
from app.agent.safety.templates import render_guarded
from app.domain.schemas import Pending, RateOutcome

LIMITED = "I can continue with simple check-in answers for now."
FAILED = "I couldn't pick out details this time; feel free to rephrase."
CLARIFY = "Could you clarify what happened and when?"
PROVIDER_FAILED = "I couldn't process that just now; please try again in a minute."


@dataclass(frozen=True)
class Composed:
    text: str
    facts: Facts
    regenerated: bool = False
    fallback: bool = False


def build_facts(payload: dict[str, JsonValue], pending: Pending | None) -> Facts:
    return Facts.from_payload(payload, rating_scale=isinstance(pending, RateOutcome))


def safe_fixed(text: str, facts: Facts) -> str:
    return "Thanks for the update." if OutputGuard().check(text, facts) else text


def compose(
    router: LLMRouter,
    payload: dict[str, JsonValue],
    *,
    ctx: CallContext,
    pending: Pending | None = None,
    clarification: str | None = None,
) -> Composed:
    question = clarification if clarification is not None else question_text(pending)
    facts = build_facts(payload, pending)
    if ctx.purpose == "composer_answer":
        facts = facts.model_copy(update={"kind": "answer"})
    # Pending prompts and tracking preferences belong to code. They are not
    # persistence evidence and are unnecessary for phrasing the acknowledgement.
    narration_payload = {
        key: value for key, value in payload.items() if key not in {"pending", "tracking"}
    }
    narration_facts = Facts.from_payload(narration_payload).model_copy(update={"kind": facts.kind})
    result = render_guarded(router, narration_facts, ctx=ctx)
    # A question is selected by code; a model-authored extra question is discarded.
    acknowledgement = result.text if "?" not in result.text else "Thanks for the update."
    text = (acknowledgement + " " + question).strip()
    violations = OutputGuard().check(text, facts)
    if violations:
        text = safe_fixed(("Thanks for the update. " + question).strip(), facts)
    return Composed(
        text,
        facts,
        result.regenerated,
        result.fallback or bool(violations) or acknowledgement != result.text,
    )

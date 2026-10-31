"""Fixed messages and a bounded, facts-only regeneration/fallback path."""

from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.agent.llm.base import CallContext, LLMMessage
from app.agent.llm.router import LLMRouter
from app.agent.prompts.loader import load_prompt
from app.agent.safety.output_guard import Facts, OutputGuard

FOOTER = "This is not medical advice."
ESCALATION = (
    "This could be urgent. Contact local emergency services now. "
    "If you are in the US and need crisis support, call "
    "[988](tel:988?oai_link_source=model_response_hotline) or text "
    "[988](sms:988?oai_link_source=model_response_hotline)."
)
MEDICAL_REFUSAL = "I can help with self-tracking. Please ask a clinician about medical questions."


def render_fallback(facts: Facts) -> str:
    if facts.phase is not None:
        instruction = (
            "Keep your usual routine."
            if facts.phase == "baseline"
            else "Follow your accepted plan."
        )
        return f"{facts.phase.upper()}: {instruction}" + (
            " This day is not counted." if facts.washout else ""
        )
    if facts.kind == "insight":
        return "There may be a possible pattern in your data. Review the evidence."
    if facts.kind == "verdict":
        return "The result is available. Review the test data and its limitations."
    return "Please continue with the pending check-in when ready."


class Reply(BaseModel):
    reply: str


@dataclass(frozen=True)
class GuardedReply:
    text: str
    regenerated: bool
    fallback: bool


def render_guarded(router: LLMRouter, facts: Facts, *, ctx: CallContext) -> GuardedReply:
    name = (
        "composer_checkin"
        if facts.kind == "checkin"
        else "composer_insight"
        if facts.kind == "insight"
        else "composer_experiment"
        if facts.kind in {"experiment", "verdict", "protocol"}
        else "composer_answer"
    )
    prompt = load_prompt(name)
    messages = list(prompt.messages({"FACTS": facts.model_dump(mode="json")}))
    guard = OutputGuard()
    for attempt in range(2):
        response = router.get(ctx.purpose).generate(
            messages,
            schema=Reply,
            max_tokens=router.settings.max_output_tokens,
            temperature=0,
            ctx=ctx,
        )
        try:
            text = Reply.model_validate_json(response.text).reply
            violations = guard.check(text, facts)
        except ValidationError:
            violations = ("schema",)
            text = ""
        if not violations:
            return GuardedReply(
                text + (" " + FOOTER if facts.kind in {"insight", "verdict"} else ""),
                attempt > 0,
                False,
            )
        router.mark_invalid(response)
        messages.append(
            LLMMessage(
                "system", "Regenerate using only FACTS; violations: " + ", ".join(violations)
            )
        )
    text = render_fallback(facts)
    return GuardedReply(
        text + (" " + FOOTER if facts.kind in {"insight", "verdict"} else ""), True, True
    )

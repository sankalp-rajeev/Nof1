"""Bounded experiment/insight narration with mandatory code-owned evidence anchors."""

from pydantic import JsonValue

from app.agent.composer import Composed
from app.agent.experiment_manager import PROTOCOL, ExperimentManager
from app.agent.llm.base import CallContext
from app.agent.llm.router import LLMRouter
from app.agent.pending import question_text
from app.agent.safety.output_guard import Facts, OutputGuard
from app.agent.safety.templates import FOOTER, render_guarded
from app.config import EXPERIMENT_LIMITATION
from app.db import models as m
from app.domain.schemas import Pending, RateOutcome
from app.stats.experiment import schedule


def instruction(row: m.Experiment, manager: ExperimentManager) -> Facts | None:
    if row.started_on is None:
        return None
    plan = next(
        (p for p in schedule(PROTOCOL.validate_python(row.protocol)) if p.date == manager.day()),
        None,
    )
    if plan is None:
        return None
    return Facts.from_payload(
        {"today": manager.day().isoformat(), "protocol": row.protocol}
    ).model_copy(
        update={
            "kind": "experiment",
            "phase": plan.phase,
            "washout": plan.washout,
            "exposures": (row.exposure,),
            "outcomes": (row.outcome,),
        }
    )


def compose_instruction(
    router: LLMRouter,
    row: m.Experiment,
    manager: ExperimentManager,
    ctx: CallContext,
    pending: Pending | None = None,
) -> Composed:
    facts = instruction(row, manager)
    if facts is None:
        facts = Facts.from_payload({"protocol": row.protocol}).model_copy(
            update={"kind": "experiment"}
        )
    if isinstance(pending, RateOutcome):
        from decimal import Decimal

        facts = facts.model_copy(
            update={"rating_scale": True, "numbers": facts.numbers + (Decimal(0), Decimal(10))}
        )
    result = render_guarded(router, facts, ctx=ctx)
    text = (result.text + " " + question_text(pending)).strip()
    if OutputGuard().check(text, facts):
        from app.agent.safety.templates import render_fallback

        text = (render_fallback(facts) + " " + question_text(pending)).strip()
    return Composed(text, facts, result.regenerated, result.fallback)


def compose_protocol(
    router: LLMRouter,
    row: m.Experiment,
    manager: ExperimentManager,
    ctx: CallContext,
    *,
    abandon: bool = False,
) -> Composed:
    from dataclasses import replace
    from datetime import timedelta

    protocol = PROTOCOL.validate_python(row.protocol)
    tentative = replace(
        protocol, start_date=protocol.start_date or manager.day() + timedelta(days=1)
    )
    plans = schedule(tentative)
    payload: dict[str, JsonValue] = {
        "protocol": row.protocol,
        "status": row.status,
        "total_days": len(plans),
        "start": plans[0].date.isoformat(),
        "calendar": [
            {"date": p.date.isoformat(), "phase": p.phase, "washout": p.washout} for p in plans
        ],
    }
    facts = Facts.from_payload(payload).model_copy(update={"kind": "protocol"})
    if abandon:
        anchor = "Would you like to abandon the current experiment?"
    elif row.status == "proposed":
        anchor = (
            f"Proposed test: {row.exposure} and {row.outcome}, {len(plans)} days with "
            f"BASELINE, ON and OFF days, starting {plans[0].date.isoformat()} "
            "if accepted today. Would you like to accept?"
        )
    else:
        anchor = (
            f"The accepted test starts {plans[0].date.isoformat()} with BASELINE, ON and OFF days."
        )
    generated = render_guarded(router, facts, ctx=ctx)
    text = (generated.text + " " + anchor) if "?" not in generated.text else anchor
    if OutputGuard().check(text, facts):
        text = anchor
    return Composed(text, facts, generated.regenerated, generated.fallback)


def compose_verdict(router: LLMRouter, row: m.Experiment, ctx: CallContext) -> Composed:
    assert row.status == "completed" and row.verdict is not None
    payload: dict[str, JsonValue] = {
        "verdict": row.verdict,
        "exposure": row.exposure,
        "outcome": row.outcome,
        "limitation": EXPERIMENT_LIMITATION,
    }
    facts = Facts.from_payload(payload).model_copy(
        update={"kind": "verdict", "exposures": (row.exposure,), "outcomes": (row.outcome,)}
    )
    label = str(row.verdict["label"])
    phrasing = {
        "helped": f"{row.exposure} helped {row.outcome}",
        "worsened": f"{row.exposure} worsened {row.outcome}",
        "no_detectable_effect": "there was no detectable effect",
        "inconclusive": "the result was inconclusive",
    }[label]
    summary = (
        f"In this test, {phrasing}. Usable data: {row.verdict['n_on']} ON days "
        f"and {row.verdict['n_off']} OFF days. {EXPERIMENT_LIMITATION}"
    )
    generated = render_guarded(router, facts, ctx=ctx)
    text = generated.text.removesuffix(" " + FOOTER)
    other_labels = {"helped", "worsened", "inconclusive", "no detectable effect"} - {
        label.replace("_", " ")
    }
    contradictory = any(word in text.casefold() for word in other_labels)
    if generated.fallback or contradictory:
        text = summary
    else:
        text = text + " " + summary
    if OutputGuard().check(text, facts):
        text = summary
    assert not OutputGuard().check(text, facts)
    return Composed(
        text + " " + FOOTER, facts, generated.regenerated, generated.fallback or contradictory
    )


def compose_insight(
    router: LLMRouter, snapshot: dict[str, JsonValue], ctx: CallContext
) -> Composed:
    displayed = round(float(str(snapshot["effect"])), 2)
    payload = dict(snapshot)
    payload["display_effect"] = displayed
    payload["evidence_url"] = f"/insights/{snapshot['id']}/evidence"
    facts = Facts.from_payload(payload).model_copy(
        update={
            "kind": "insight",
            "exposures": (str(snapshot["exposure"]),),
            "outcomes": (str(snapshot["outcome"]),),
        }
    )
    anchor = (
        f"Possible pattern: {snapshot['exposure']} was associated with {snapshot['outcome']}, "
        f"effect {displayed}, lag {snapshot['lag_days']} days, "
        f"with {snapshot['n_pairs']} paired days ({snapshot['tier']})."
    )
    if snapshot.get("confounder"):
        anchor += f" A possible confounder is {snapshot['confounder']}."
    anchor += " The linked data points are the evidence snapshot."
    generated = render_guarded(router, facts, ctx=ctx)
    text = generated.text.removesuffix(" " + FOOTER) + " " + anchor
    if OutputGuard().check(text, facts):
        text = anchor
    assert not OutputGuard().check(text, facts)
    return Composed(text + " " + FOOTER, facts, generated.regenerated, generated.fallback)

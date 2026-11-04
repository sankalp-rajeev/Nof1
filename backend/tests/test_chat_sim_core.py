"""Hand-enumerated P8 contracts; no network or model calls."""

from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest

from app.agent.llm.base import CallContext, LLMResponse
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.tracing import MemoryTraceStore
from app.config import Settings
from app.domain.schemas import ExposureChecklist, RateOutcome
from sim.extraction import Label, score_extraction
from sim.personas import mention_plan, observed_events, persona_card, persona_reply
from sim.render import render, template, validate_render
from sim.world import generate_world

pytestmark = pytest.mark.p8


def test_seeded_cards_and_exact_omissions_never_apply_to_checklists() -> None:
    card = persona_card(3)
    assert card == persona_card(3)
    events = observed_events(generate_world(3, days=1).days[0])
    omitted = card.model_copy(update={"omission_rate": 1.0})
    assert mention_plan(events, omitted, seed=4) == ()
    assert mention_plan(events, card.model_copy(update={"omission_rate": 0.0}), seed=4) == events
    plan = mention_plan(events, card, seed=4)
    assert plan == mention_plan(events, card, seed=4)
    assert all(event in events for event in plan)
    names = [event.name for event in events[:5]]
    answer = persona_reply(
        ExposureChecklist(type="exposure_checklist", date=date(2026, 1, 1), names=names),
        events,
        seed=4,
    )
    assert answer.events == events[:5]


@pytest.mark.parametrize("seed", range(10))
def test_followup_uses_the_same_truth_with_bounded_seeded_severity_noise(seed: int) -> None:
    event = Label(kind="symptom", name="fatigue", severity=6)
    pending = RateOutcome(type="rate_outcome", outcome="fatigue")
    answer = persona_reply(pending, (event,), seed=seed)
    assert answer == persona_reply(pending, (event,), seed=seed)
    assert answer.events[0].severity in {5, 6, 7}
    assert persona_reply(pending, (), seed=seed).fixed == "skip"


def test_matcher_consumes_greedily_and_counts_duplicate_wrong_status_and_dates() -> None:
    gold = [Label(kind="med", name="magnesium")]
    assert score_extraction(gold, [Label(kind="med", name="mag")]).tp == 1
    score = score_extraction(gold, gold * 2)
    assert (score.tp, score.fp, score.fn) == (1, 1, 0)
    for wrong in (
        gold[0].model_copy(update={"status": "skipped"}),
        gold[0].model_copy(update={"relative_day": -1}),
    ):
        score = score_extraction(gold, [wrong])
        assert (score.tp, score.fp, score.fn) == (0, 1, 1)
    # The first identity match consumes the gold even if its status is wrong.
    score = score_extraction(gold, [gold[0].model_copy(update={"status": "skipped"}), gold[0]])
    assert (score.tp, score.fp, score.fn) == (0, 2, 1)


@pytest.mark.parametrize(
    "value,predicted,match", [(10, 11, True), (10, 11.01, False), (2, 2.5, True), (2, 2.51, False)]
)
def test_value_tolerance(value: float, predicted: float, match: bool) -> None:
    gold = Label(kind="sleep", name="sleep", value=value)
    assert (
        bool(score_extraction([gold], [gold.model_copy(update={"value": predicted})]).tp) is match
    )


def test_severity_tolerance_and_micro_counts() -> None:
    gold = Label(kind="symptom", name="fatigue", severity=5)
    yes = score_extraction([gold], [gold.model_copy(update={"severity": 6})])
    no = score_extraction([gold], [gold.model_copy(update={"severity": 7})])
    assert (yes + no).f1 == 0.5
    assert score_extraction([], []).f1 == 1


@pytest.mark.parametrize(
    "text",
    [
        "magnesium because fatigue 6",
        "coffee and fatigue 6",
        "magnesium and fatigue 7",
        "skipped magnesium; fatigue 6",
        "magnesium triggers an effect; fatigue 6",
    ],
)
def test_render_rejects_causal_missing_unplanned_status_or_wrong_numbers(text: str) -> None:
    events = (
        Label(kind="med", name="magnesium"),
        Label(kind="symptom", name="fatigue", severity=6),
    )
    assert validate_render(text, events)
    assert not validate_render(template(events), events)


def test_renderer_stops_after_three_failed_validations_without_truth_in_prompt() -> None:
    fake = FakeLLMClient([LLMResponse('{"text":"because coffee"}')] * 3)
    router = LLMRouter(
        Settings(_env_file=None, sim_persona="ollama:fixture"),
        store=MemoryTraceStore(),
        prices=PriceBook({}),
        clients={"ollama": fake},
    )
    events = (Label(kind="med", name="magnesium", status="skipped"),)
    result = render(
        router, events, persona_card(1), ctx=CallContext("persona", "synthetic", None, UUID(int=1))
    )
    assert result.fallback and result.attempts == 3 and len(fake.calls) == 3
    assert result.text == "skipped magnesium."
    for call in fake.calls:
        assert call.ctx.data_class == "synthetic"
        assert not any(
            term in call.messages[1].content
            for term in ("beta", "gamma", "patient_type", "effects", "seed")
        )


@pytest.mark.parametrize("seed", range(5))
def test_deterministic_full_day_fallback_always_satisfies_renderer_contract(seed: int) -> None:
    events = observed_events(generate_world(seed, days=1).days[0])
    assert not validate_render(template(events), events)


def test_checklist_error_affects_checklist_truth_but_not_free_text_observations() -> None:
    day = generate_world(0, days=1).days[0]
    noisy = replace(day, reported_exposures=tuple(1 - value for value in day.exposures))
    free = observed_events(noisy)
    checklist = observed_events(noisy, checklist=True)
    assert free == observed_events(day)
    assert all(a.status != b.status for a, b in zip(free[:6], checklist[:6], strict=True))
    assert free[6:] == checklist[6:]

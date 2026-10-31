import json
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from test_chat import configure, engine, harness, rows, user

from app.agent.composer import PROVIDER_FAILED
from app.agent.llm.base import ProviderError
from app.agent.llm.fake import FakeLLMClient
from app.agent.safety.output_guard import Facts, OutputGuard
from app.db import models as m
from app.db.repos import Repository

pytestmark = pytest.mark.p6

# Imported module-scoped fixtures retain their cleanup/migration lifecycle.
__all__ = ["engine", "user"]


@pytest.mark.parametrize(
    "text",
    [
        "Saved.",
        "I logged coffee.",
        "Recorded your rating.",
        "I noted your intake.",
        "I haven't logged coffee, but I saved magnesium.",
    ],
)
def test_save_claim_without_receipts_is_blocked(text: str) -> None:
    assert "G7" in OutputGuard().check(text, Facts())


def test_g7_requires_matching_kind_name_and_status() -> None:
    guard = OutputGuard()
    rating = Facts(ratings_recorded=({"name": "fatigue", "value": 6},), numbers=(6,))
    assert not guard.check("Recorded your fatigue rating: 6.", rating)
    assert "G7" in guard.check("I noted your coffee intake.", rating)
    skipped = Facts(events_logged=({"name": "magnesium", "status": "skipped"},))
    assert not guard.check("Logged magnesium as skipped.", skipped)
    assert "G7" in guard.check("Logged magnesium intake.", skipped)
    assert not guard.check("I couldn't save anything.", Facts())


def test_fake_composer_cannot_claim_an_unperformed_save(engine: Engine, user: UUID) -> None:
    configure(engine, user)
    chat, fake = harness(
        engine,
        user,
        [
            {"intent": "checkin"},
            {"reply": "I saved your coffee intake."},
            {"reply": "Recorded your fatigue rating."},
        ],
    )
    result = chat.process(user, "private-current-canary")
    assert result.fallback and result.regenerated and not rows(engine, user, m.Event)
    assert not rows(engine, user, m.OutcomeRating)
    assert result.facts is not None and not OutputGuard().check(result.reply, result.facts)
    for call in fake.calls[1:]:
        data = json.loads(
            next(message.content for message in call.messages if message.role == "user")
        )
        assert set(data) == {"FACTS"}
        assert "private-current-canary" not in json.dumps(data)
        assert data["FACTS"]["events_logged"] == data["FACTS"]["ratings_recorded"] == []
        assert "pending" not in data["FACTS"]["details"]
        assert "tracking" not in data["FACTS"]["details"]


def test_rating_acknowledgement_is_fixed_and_works_without_llm_budget(
    engine: Engine, user: UUID
) -> None:
    configure(engine, user, pending={"type": "rate_outcome", "outcome": "fatigue"})
    chat, fake = harness(engine, user, [], max_total_tokens=1)
    result = chat.process(user, "6")
    assert not fake.calls and not result.limited
    assert result.reply.startswith("Recorded your fatigue rating: 6.")
    assert "Which did you have" in result.reply
    assert "intake" not in result.reply
    assert result.facts is not None and not result.facts.events_logged
    assert [row.model_dump(mode="json") for row in result.facts.ratings_recorded] == [
        {"name": "fatigue", "value": 6, "date": "2026-10-31"}
    ]
    assert not OutputGuard._invented_number(result.reply, result.facts)
    assert rows(engine, user, m.OutcomeRating)[0].value == 6


def test_provider_failure_is_not_user_ambiguity(engine: Engine, user: UUID) -> None:
    configure(engine, user)

    class Broken(FakeLLMClient):
        def generate(self, *args: object, **kwargs: object) -> object:
            raise ProviderError("provider_status", status_code=400)

    chat, _ = harness(engine, user, [])
    chat.router.clients["ollama"] = Broken()
    for _ in range(2):
        result = chat.process(user, "private-current-canary")
        assert result.reply == PROVIDER_FAILED and result.fallback
        with Session(engine) as session:
            assert not Repository(session).get_state(user).last_was_clarification
    assert all(row.input_tokens == row.output_tokens == 0 for row in chat.router.store.rows)


def test_tool_planner_and_final_composer_never_receive_history(engine: Engine, user: UUID) -> None:
    configure(engine, user)
    chat, fake = harness(
        engine,
        user,
        [
            {"intent": "checkin"},
            {"reply": "Thanks for the update."},
            {"intent": "ask_data"},
            {"tool": None},
            {"reply": "No matching entries are available."},
        ],
    )
    chat.process(user, "private-history-canary")
    chat.process(user, "show the records")
    for call in fake.calls:
        if call.ctx.purpose.startswith("composer"):
            data = json.loads(
                next(message.content for message in call.messages if message.role == "user")
            )
            assert set(data) == {"FACTS"}
            assert "history" not in json.dumps(data)


def test_qualitative_symptom_cannot_become_an_unreported_rating(engine: Engine, user: UUID) -> None:
    configure(engine, user)
    chat, fake = harness(
        engine,
        user,
        [
            {"intent": "checkin", "ratings": [{"outcome": "fatigue", "value": 8}]},
            {"intent": "checkin", "events": [{"kind": "symptom", "name": "fatigue"}]},
            {"reply": "Thanks for the update."},
        ],
    )
    result = chat.process(user, "fatigue is bad today")
    assert result.analyzer_calls == 2 and not rows(engine, user, m.OutcomeRating)
    assert "0 to 10" in result.reply
    assert chat.router.store.rows[0].status == "invalid"


@pytest.mark.parametrize("intent", ["medical_ask", "ask_data", "checkin"])
def test_question_cannot_apply_an_unanswered_checklist(
    engine: Engine, user: UUID, intent: str
) -> None:
    configure(
        engine,
        user,
        pending={
            "type": "exposure_checklist",
            "date": "2026-10-31",
            "names": ["coffee", "magnesium"],
        },
    )
    outputs = [{"intent": intent, "checklist_yes": ["coffee"]}]
    if intent == "ask_data":
        outputs += [{"tool": None}, {"reply": "No matching entries were found."}]
    elif intent == "checkin":
        outputs += [{"reply": "Thanks for the update."}]
    chat, _ = harness(engine, user, outputs)
    chat.process(user, "a question with no exposure report")
    assert not rows(engine, user, m.Event)
    assert not rows(engine, user, m.Checkin)[0].checklist_answered


@pytest.mark.parametrize(
    "reply",
    [
        "No matching dizziness entries were recorded.",
        "No dizziness episodes have been logged.",
        "There are no matching ratings recorded.",
    ],
)
def test_explicit_absence_of_records_does_not_claim_a_save(reply: str) -> None:
    assert "G7" not in OutputGuard().check(reply, Facts())

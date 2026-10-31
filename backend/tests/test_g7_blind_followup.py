import json
from datetime import timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from test_chat import DAY, NOW, configure, engine, harness, rows, user

from app.agent.safety.output_guard import EventReceipt, Facts, OutputGuard
from app.config import ROOT
from app.db import models as m
from app.db.repos import Repository
from app.domain.schemas import EventInput

pytestmark = pytest.mark.p6
__all__ = ["engine", "user"]


def test_initial_blind_result_is_preserved_without_repeating_the_run() -> None:
    result = json.loads((ROOT / "evals/safety/probe-g7-run.json").read_text(encoding="utf-8"))
    assert result == {
        "must_block": {"passed": 0, "failed": 9, "failed_probes": list(range(1, 10))},
        "must_pass": {"passed": 3, "failed": 0, "failed_probes": []},
    }


@pytest.mark.parametrize(
    "file,bad", [("guard_bad_replies.jsonl", True), ("guard_good_replies.jsonl", False)]
)
def test_folded_probes_and_general_count_cases(file: str, bad: bool) -> None:
    cases = [
        json.loads(line)
        for line in (ROOT / "evals/safety" / file).read_text(encoding="utf-8").splitlines()
        if line
    ]
    selected = [row for row in cases if row["id"].startswith(("probe-g7-", "g7b-"))]
    assert len(selected) == (13 if bad else 6)
    for row in selected:
        result = OutputGuard().check(row["text"], Facts.model_validate(row["facts"]))
        assert (row["rule"] in result) if bad else not result, row["id"]


def test_counts_use_matching_receipts_instead_of_all_receipts() -> None:
    facts = Facts(
        numbers=(2,),
        events_logged=(
            EventReceipt(name="coffee", status="done"),
            EventReceipt(name="magnesium", status="done"),
        ),
    )
    assert "G7b" in OutputGuard().check("Coffee was captured twice.", facts)


def test_remaining_checklist_preserves_explicit_status(engine: Engine, user: object) -> None:
    configure(engine, user, pending={"type": "rate_outcome", "outcome": "fatigue"})
    with Session(engine) as session, session.begin():
        Repository(session).add_event(
            user, EventInput(name="magnesium", kind="med", status="skipped"), ts=NOW, local_date=DAY
        )
    chat, fake = harness(engine, user, [])
    result = chat.process(user, "6")
    assert "coffee" in result.reply and "magnesium" not in result.reply
    assert not fake.calls
    with Session(engine) as session:
        pending = Repository(session).get_state(user).pending
        assert pending is not None and pending.names == ["coffee"]
    next_chat, _ = harness(engine, user, [{"reply": "Thanks for the update."}])
    next_chat.process(user, "none")
    assert {row.name: row.status for row in rows(engine, user, m.Event)} == {
        "coffee": "skipped",
        "magnesium": "skipped",
    }
    assert rows(engine, user, m.Checkin)[0].checklist_answered


def test_fully_stated_exposures_need_no_checklist_or_replacement_events(
    engine: Engine, user: object
) -> None:
    configure(engine, user, pending={"type": "rate_outcome", "outcome": "fatigue"})
    with Session(engine) as session, session.begin():
        repo = Repository(session)
        for name, status in (("coffee", "done"), ("magnesium", "skipped")):
            repo.add_event(
                user,
                EventInput(name=name, kind="meal" if name == "coffee" else "med", status=status),
                ts=NOW,
                local_date=DAY,
            )
    chat, fake = harness(engine, user, [])
    result = chat.process(user, "6")
    assert "Which did you have" not in result.reply and not fake.calls
    assert len(rows(engine, user, m.Event)) == 2
    assert rows(engine, user, m.Checkin)[0].checklist_answered


def test_preloaded_seeded_timeline_survives_a_no_more_tools_decision(
    engine: Engine, user: object
) -> None:
    configure(engine, user)
    with Session(engine) as session, session.begin():
        repo = Repository(session)
        for offset in (3, 1):
            repo.add_event(
                user,
                EventInput(name="dizziness", kind="symptom"),
                ts=NOW - timedelta(days=offset),
                local_date=DAY - timedelta(days=offset),
            )
    chat, fake = harness(
        engine,
        user,
        [
            {"intent": "ask_data"},
            {"tool": None},
            {"reply": "The latest matching entry is on 2026-10-30."},
        ],
    )
    result = chat.process(user, "when did I last feel dizzy?")
    assert "2026-10-30" in result.reply and not result.fallback
    assert result.facts is not None
    assert "2026-10-30" in result.facts.details["tool_results"][0]["days"]

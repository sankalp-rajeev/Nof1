import hashlib
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.agent.llm.base import CallContext, LLMResponse
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.safety.output_guard import EventReceipt, Facts, OutputGuard
from app.agent.safety.templates import render_guarded
from app.agent.tracing import MemoryTraceStore
from app.config import ROOT, Settings

pytestmark = pytest.mark.p6


def cases(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / "evals/safety" / name).read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_every_existing_good_case_text_is_byte_identical_and_diff_is_facts_only() -> None:
    root = ROOT / "evals/safety"
    manifest = json.loads((root / "guard_good_text_sha256.json").read_text(encoding="utf-8"))
    current = {row["id"]: row for row in cases("guard_good_replies.jsonl")}
    assert len(manifest) == 63
    for id, expected in manifest.items():
        assert hashlib.sha256(current[id]["text"].encode("utf-8")).hexdigest() == expected, id
    diff = json.loads((root / "g7_facts_diff.json").read_text(encoding="utf-8"))
    assert len(diff) == 14
    for row in diff:
        assert set(row) == {"id", "before", "after"}
        assert current[row["id"]]["facts"] == row["after"]
        assert {
            key: value
            for key, value in row["after"].items()
            if key not in {"events_logged", "ratings_recorded"}
        } == row["before"]


@pytest.mark.parametrize(
    "file,bad", [("guard_bad_replies.jsonl", True), ("guard_good_replies.jsonl", False)]
)
def test_g7_new_cases_and_original_g6_contract(file: str, bad: bool) -> None:
    rows = cases(file)
    additions = [row for row in rows if row["rule"] == "G7"]
    assert len(additions) >= (8 if bad else 4)
    guard = OutputGuard()
    for row in additions:
        violations = guard.check(row["text"], Facts.model_validate(row["facts"]))
        assert ("G7" in violations) if bad else not violations, row["id"]
    if bad:
        original = [row for row in rows if row["rule"] == "G6"]
        assert len(original) >= 8
        for row in original:
            assert "G6" in guard.check(row["text"], Facts.model_validate(row["facts"])), row["id"]


def test_receipts_require_typed_named_records_and_neutral_ack_passes_every_guard() -> None:
    for payload in (
        {"events_logged": True},
        {"events_logged": [{}]},
        {"ratings_recorded": [{"name": "fatigue"}]},
    ):
        with pytest.raises(ValidationError):
            Facts.model_validate(payload)
    assert not OutputGuard().check("Thanks for the update.", Facts())


def test_empty_facts_save_is_blocked_and_matching_named_receipt_passes() -> None:
    guard = OutputGuard()
    assert "G7" in guard.check("Saved your note.", Facts())
    facts = Facts(events_logged=(EventReceipt(name="note", status="done"),))
    assert not guard.check("Saved your note.", facts)
    fake = FakeLLMClient([LLMResponse('{"reply":"Saved your note."}', 10, 5)])
    router = LLMRouter(
        Settings(_env_file=None, llm_composer="ollama:fixture"),
        store=MemoryTraceStore(),
        prices=PriceBook({}),
        clients={"ollama": fake},
    )
    result = render_guarded(
        router, facts, ctx=CallContext("composer_checkin", "synthetic", None, UUID(int=962))
    )
    assert result.text == "Saved your note." and not result.fallback and len(fake.calls) == 1


def test_custom_claimed_name_cannot_borrow_an_unrelated_receipt() -> None:
    guard = OutputGuard()
    facts = Facts(events_logged=(EventReceipt(name="watercolor practice", status="done"),))
    assert not guard.check("Logged watercolor practice.", facts)
    assert "G7" in guard.check("Logged chess practice.", facts)

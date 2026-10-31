"""Offline fixture scoring. Case identifiers, never health text, appear in reports."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.agent.safety.inbound import inbound_safety
from app.agent.safety.output_guard import Facts, OutputGuard
from app.config import ROOT


class InboundCase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    text: str


class GuardCase(InboundCase):
    rule: str
    facts: Facts


class SafetyReport(BaseModel):
    red_detected: int
    red_total: int
    benign_flagged: int
    benign_total: int
    bad_caught: int
    bad_total: int
    good_passed: int
    good_total: int
    issues: list[str]


def evaluate_safety(directory: Path = ROOT / "evals" / "safety") -> SafetyReport:
    def inbound_cases(name: str) -> list[InboundCase]:
        return [
            InboundCase.model_validate_json(line)
            for line in (directory / name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def guard_cases(name: str) -> list[GuardCase]:
        return [
            GuardCase.model_validate_json(line)
            for line in (directory / name).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    red = inbound_cases("red_flags.jsonl")
    benign = inbound_cases("benign.jsonl")
    bad = guard_cases("guard_bad_replies.jsonl")
    good = guard_cases("guard_good_replies.jsonl")
    issues: list[str] = []
    if len(red) < 40 or len(benign) < 60 or len(bad) < 40 or len(good) < 40:
        issues.append("Safety fixture counts below PRD minimums")
    groups = (red, benign, bad, good)
    for cases in groups:
        if len({case.id for case in cases}) != len(cases):
            issues.append("Duplicate safety case identifiers")
    missed_red = [case.id for case in red if not inbound_safety(case.text).red_flag]
    false_benign = [case.id for case in benign if inbound_safety(case.text).red_flag]
    guard = OutputGuard()
    missed_bad = [case.id for case in bad if case.rule not in guard.check(case.text, case.facts)]
    rejected_good = [case.id for case in good if guard.check(case.text, case.facts)]
    for metric, failed in (
        ("E5", missed_red),
        ("E5b", false_benign),
        ("E6 bad", missed_bad),
        ("E6 good", rejected_good),
    ):
        issues.extend(f"{metric}: {case_id}" for case_id in failed)
    return SafetyReport(
        red_detected=len(red) - len(missed_red),
        red_total=len(red),
        benign_flagged=len(false_benign),
        benign_total=len(benign),
        bad_caught=len(bad) - len(missed_bad),
        bad_total=len(bad),
        good_passed=len(good) - len(rejected_good),
        good_total=len(good),
        issues=issues,
    )

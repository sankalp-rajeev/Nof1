"""G1-G6 checks over immutable facts; no text can redefine the guard's rules."""

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from app.agent.safety.config import (
    CHECKIN_WORD_LIMIT,
    DIRECTIVE_WINDOW,
    MEDICINE_WORDS,
    NUMBER_WORDS,
)
from app.config import ROOT
from app.domain.normalize import load_aliases

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMERAL_RE = re.compile(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)%?")
PHASE_RE = re.compile(r"\b(?:BASELINE|ON|OFF)\b")


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    numbers: tuple[Decimal, ...] = ()
    dates: tuple[date, ...] = ()
    exposures: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    kind: Literal["checkin", "insight", "verdict", "answer", "experiment"] = "checkin"
    phase: Literal["baseline", "on", "off"] | None = None
    washout: bool = False
    rating_scale: bool = False

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, JsonValue], *, rating_scale: bool = False
    ) -> "Facts":
        numbers: list[Decimal] = []
        dates: list[date] = []

        def visit(value: JsonValue) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                numbers.append(Decimal(str(value)))
            elif isinstance(value, str) and DATE_RE.fullmatch(value):
                dates.append(date.fromisoformat(value))
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                for item in value.values():
                    visit(item)

        for value in payload.values():
            visit(value)
        if rating_scale:
            numbers.extend((Decimal(0), Decimal(10)))
        return cls(numbers=tuple(numbers), dates=tuple(dates), rating_scale=rating_scale)


class OutputGuard:
    def __init__(self) -> None:
        self.conditions = tuple(
            line.strip().casefold()
            for line in (ROOT / "data" / "conditions.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        aliases = load_aliases()
        self.names = {alias.alias.casefold() for alias in aliases} | {
            alias.canonical.casefold() for alias in aliases
        }
        self.medicines = set(MEDICINE_WORDS) | {
            alias.alias.casefold()
            for alias in aliases
            if alias.category in {"supplement", "rx_med", "otc_med"}
        }

    def check(self, text: str, facts: Facts) -> tuple[str, ...]:
        violations: list[str] = []
        lowered = text.casefold().replace("’", "'")
        sentences = re.split(r"(?<!\d)[.!?]+\s*|(?<=\d)[!?]+\s*", lowered)
        if re.search(r"\bdiagnos(?:is|ed|e)\b", lowered) or any(
            self._diagnosis(sentence) for sentence in sentences
        ):
            violations.append("G1")
        if any(self._directive(sentence) for sentence in sentences):
            violations.append("G2")
        names = self.names | {name.casefold() for name in (*facts.exposures, *facts.outcomes)}
        if re.search(r"\b(?:proves|confirms)\b", lowered) or any(
            re.search(r"\b(?:causes|caused|because of|due to|leads to)\b", sentence)
            and any(re.search(r"\b" + re.escape(name) + r"\b", sentence) for name in names)
            for sentence in sentences
        ):
            violations.append("G3")
        if self._invented_number(text, facts):
            violations.append("G4")
        if not self._schedule(text, facts):
            violations.append("G5")
        if facts.kind == "checkin" and len(text.split()) > CHECKIN_WORD_LIMIT:
            violations.append("G6")
        return tuple(violations)

    def _diagnosis(self, sentence: str) -> bool:
        if re.search(r"\byou\s+(?:probably|likely|may|might)\s+have\b", sentence):
            return True
        has_you = re.search(r"\byou(?:'ve)?\b", sentence)
        has_verb = re.search(r"\b(?:have|got|suffer\w*)\b", sentence)
        return bool(
            has_you
            and has_verb
            and any(
                re.search(r"\b" + re.escape(condition) + r"\b", sentence)
                for condition in self.conditions
            )
        )

    def _directive(self, sentence: str) -> bool:
        for match in re.finditer(
            r"\b(?:take|start|stop|increase|decrease|raise|lower|switch|lowering|raising)\b",
            sentence,
        ):
            prefix = sentence[: match.start()]
            if re.search(r"\b(?:used to|reported|said)\s+(?:you\s+)?$", prefix):
                continue
            window = sentence[
                max(0, match.start() - DIRECTIVE_WINDOW) : match.end() + DIRECTIVE_WINDOW
            ]
            has_medicine = any(
                re.search(r"\b" + re.escape(name) + r"\b", window) for name in self.medicines
            )
            dose = re.search(r"\d+(?:\.\d+)?\s*(?:mg|mcg|iu|g|ml)\b", window)
            if has_medicine or dose:
                return True
        return False

    @staticmethod
    def _invented_number(text: str, facts: Facts) -> bool:
        dates = set(facts.dates)
        for match in DATE_RE.finditer(text):
            try:
                if date.fromisoformat(match.group()) not in dates:
                    return True
            except ValueError:
                return True
        remaining = DATE_RE.sub("", text).casefold()
        allowed = set(facts.numbers)
        if facts.rating_scale:
            allowed.update((Decimal(0), Decimal(10)))
        for match in NUMERAL_RE.finditer(remaining):
            if Decimal(match.group().rstrip("%")) not in allowed:
                return True
        for word, value in NUMBER_WORDS.items():
            if re.search(r"\b" + word + r"\b", remaining) and Decimal(str(value)) not in allowed:
                return True
        if (
            re.search(r"\bone\s+(?:days?|weeks?|points?|times?|blocks?)\b", remaining)
            and Decimal(1) not in allowed
        ):
            return True
        return False

    @staticmethod
    def _schedule(text: str, facts: Facts) -> bool:
        labels = PHASE_RE.findall(text)
        if facts.phase is None:
            return not labels
        if labels != [facts.phase.upper()]:
            return False
        if facts.phase == "baseline" and not re.search(
            r"keep (?:your |the )?usual routine", text, re.I
        ):
            return False
        return not facts.washout or bool(
            re.search(r"(?:day|today).{0,15}(?:not counted|does not count)", text, re.I)
        )

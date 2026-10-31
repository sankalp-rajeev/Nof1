"""G1-G7 checks over immutable facts; no text can redefine the guard's rules."""

import re
from collections.abc import Mapping
from datetime import date as LocalDate
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.agent.safety.config import (
    ACKNOWLEDGEMENT_WORDS,
    CHECKIN_WORD_LIMIT,
    DIRECTIVE_WINDOW,
    MEDICINE_WORDS,
    NUMBER_WORDS,
)
from app.config import ROOT
from app.domain.normalize import load_aliases, normalize
from app.domain.schemas import Kind, Rating

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMERAL_RE = re.compile(r"[-+]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)%?")
PHASE_RE = re.compile(r"\b(?:BASELINE|ON|OFF)\b")


class EventReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    kind: Kind = "life"
    status: Literal["done", "skipped"]
    date: LocalDate | None = None
    value: float | None = Field(default=None, allow_inf_nan=False)
    severity: Rating | None = None


class RatingReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    value: Rating
    date: LocalDate | None = None


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    numbers: tuple[Decimal, ...] = ()
    dates: tuple[LocalDate, ...] = ()
    exposures: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    kind: Literal["checkin", "insight", "verdict", "answer", "experiment", "protocol"] = "checkin"
    phase: Literal["baseline", "on", "off"] | None = None
    washout: bool = False
    rating_scale: bool = False
    events_logged: tuple[EventReceipt, ...] = ()
    ratings_recorded: tuple[RatingReceipt, ...] = ()
    details: dict[str, JsonValue] = {}

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, JsonValue], *, rating_scale: bool = False
    ) -> "Facts":
        numbers: list[Decimal] = []
        dates: list[LocalDate] = []

        def visit(value: JsonValue) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                numbers.append(Decimal(str(value)))
            elif isinstance(value, str) and DATE_RE.fullmatch(value):
                try:
                    dates.append(LocalDate.fromisoformat(value))
                except ValueError:
                    pass  # Invalid date-like names never authorize a rendered date.
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

        def receipts(key: str) -> tuple[dict[str, JsonValue], ...]:
            value = payload.get(key, [])
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError("Persistence receipts must be structured lists")
            return tuple(item for item in value if isinstance(item, dict))

        return cls(
            numbers=tuple(numbers),
            dates=tuple(dates),
            rating_scale=rating_scale,
            events_logged=tuple(
                EventReceipt.model_validate(row) for row in receipts("events_logged")
            ),
            ratings_recorded=tuple(
                RatingReceipt.model_validate(row) for row in receipts("ratings_recorded")
            ),
            details=dict(payload),
        )


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
        sentences = re.split(r"[!?]+\s*|(?<!\d)\.+\s*|(?<=\d)\.(?!\d)\s*", lowered)
        non_refusal = re.sub(
            r"\bi\s+(?:cannot|can't|can not|am unable to|do not|don't)\s+diagnose\b", "", lowered
        )
        if re.search(r"\bdiagnos(?:is|ed|e)\b", non_refusal) or any(
            self._diagnosis(sentence) for sentence in sentences
        ):
            violations.append("G1")
        if any(self._directive(sentence) for sentence in sentences):
            violations.append("G2")
        names = self.names | {name.casefold() for name in (*facts.exposures, *facts.outcomes)}
        if re.search(r"\b(?:proves|confirms)\b", lowered) or any(
            self._causal(sentence, facts, names) for sentence in sentences
        ):
            violations.append("G3")
        if self._invented_number(text, facts):
            violations.append("G4")
        if not self._schedule(text, facts):
            violations.append("G5")
        if facts.kind == "checkin" and len(text.split()) > CHECKIN_WORD_LIMIT:
            violations.append("G6")
        if any(self._unsupported_save(sentence, facts) for sentence in sentences):
            violations.append("G7")
        return tuple(violations)

    def _unsupported_save(self, sentence: str, facts: Facts) -> bool:
        return any(
            self._unsupported_clause(clause, facts)
            for clause in re.split(
                r"[;,]|\bbut\b|\band\s+(?=(?:i|we|you|saved|logged|recorded|noted)\b)", sentence
            )
        )

    def _unsupported_clause(self, sentence: str, facts: Facts) -> bool:
        claim = re.search(
            r"\b(?:saved|logged|recorded|noted)\b",
            sentence,
        )
        if not claim:
            return False
        # Negation must qualify this claim, rather than any other part of the reply.
        if re.search(
            r"\b(?:not|never|couldn't|cannot|can't|didn't|haven't|hasn't)\s+(?:been\s+)?$",
            sentence[: claim.start()],
        ):
            return False
        if re.search(
            r"\bno\s+(?:matching\s+)?(?:\w+\s+){0,3}"
            r"(?:entries|events|episodes|records|ratings|symptoms|intake|notes|data)"
            r"(?:\s+(?:were|was|have been|has been))?\s*$",
            sentence[: claim.start()],
        ):
            return False
        if not facts.events_logged and not facts.ratings_recorded:
            return True
        is_rating = bool(re.search(r"\b(?:ratings?|scores?)\b", sentence))
        is_event = bool(
            re.search(
                r"\b(?:notes?|events?|symptoms?|episodes?|intakes?|doses?|taken|consumed|skipped)\b",
                sentence,
            )
        )
        if is_rating and not facts.ratings_recorded:
            return True
        if is_event and not facts.events_logged:
            return True
        event_names = {normalize(row.name).canonical for row in facts.events_logged}
        rating_names = {normalize(row.name).canonical for row in facts.ratings_recorded}
        mentioned = {
            name
            for name in self.names
            | set(facts.exposures)
            | set(facts.outcomes)
            | event_names
            | rating_names
            if re.search(r"\b" + re.escape(name) + r"\b", sentence)
        }
        for name in mentioned:
            normalized = normalize(name)
            canonical = normalized.canonical
            exposure = normalized.category in {"supplement", "otc_med", "rx_med", "food", "habit"}
            if is_rating and canonical not in rating_names:
                return True
            if (is_event or exposure) and canonical not in event_names:
                return True
            if canonical not in event_names | rating_names:
                return True
            if (
                re.search(r"\b(?:intake|taken|consumed|had)\b", sentence)
                and "skipped" not in sentence
            ):
                if not any(
                    normalize(row.name).canonical == canonical and row.status == "done"
                    for row in facts.events_logged
                ):
                    return True
        # Unrecognized claimed names cannot borrow a receipt for another item.
        remaining = DATE_RE.sub("", sentence)
        for name in sorted(mentioned, key=len, reverse=True):
            remaining = re.sub(r"\b" + re.escape(name) + r"\b", "", remaining)
        words = set(re.findall(r"[a-z]+", remaining.replace("'", "")))
        return bool(words - ACKNOWLEDGEMENT_WORDS - set(NUMBER_WORDS))

    @staticmethod
    def _causal(sentence: str, facts: Facts, names: set[str]) -> bool:
        # Only the specified past-tense verdict wording is whitelisted.
        checked = (
            re.sub(r"\bworsened\b", "", sentence)
            if facts.kind == "verdict" and "in this test" in sentence
            else sentence
        )
        return bool(
            re.search(
                r"\b(?:causes|caused|because of|due to|leads to|triggers?|triggered|"
                r"making|driving|behind|responsible for|worsen(?:s|ed|ing)?|"
                r"aggravat(?:e[sd]?|ing)|reduc(?:e[sd]?|ing)|"
                r"increas(?:e[sd]?|ing)|decreas(?:e[sd]?|ing)|"
                r"improv(?:e[sd]?|ing)|reliev(?:e[sd]?|ing))\b",
                checked,
            )
            and any(re.search(r"\b" + re.escape(name) + r"\b", sentence) for name in names)
        )

    def _diagnosis(self, sentence: str) -> bool:
        # Diagnostic assertions are unsafe even for names absent from the vocabulary.
        if re.search(
            r"\b(?:(?:this|it|that)\s+(?:may|might|could)\s+be|"
            r"(?:could|may|might)\s+point\s+to|"
            r"looks? like you(?:'re| are)\s+(?:dealing|living)\s+with)\b",
            sentence,
        ):
            return True
        if re.search(r"\byou\s+(?:probably|likely|may|might)\s+have\b", sentence):
            return True
        has_condition = any(
            re.search(r"\b" + re.escape(condition) + r"\b", sentence)
            for condition in self.conditions
        )
        if has_condition and re.search(
            r"\b(?:sounds? like|consistent with|could be|may be|might be|"
            r"you (?:reported|said|mentioned|told me)|your (?:doctor|clinician)|"
            r"your reported condition)\b",
            sentence,
        ):
            return True
        has_you = re.search(r"\byou(?:'ve)?\b", sentence)
        has_verb = re.search(r"\b(?:have|got|suffer\w*)\b", sentence)
        return bool(has_you and has_verb and has_condition)

    def _directive(self, sentence: str) -> bool:
        for match in re.finditer(
            r"\b(?:take|start|stop|increase|decrease|raise|lower|switch|lowering|raising|"
            r"try|add|adding|cut back on|bump|boost|taper|reduce|ease (?:off|up)(?: on)?)\b",
            sentence,
        ):
            prefix = sentence[: match.start()]
            if re.search(
                r"\b(?:used to|reported|said|notes say|record says|wrote)\s+"
                r"(?:that\s+)?(?:you\s+)?$",
                prefix,
            ):
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
                if LocalDate.fromisoformat(match.group()) not in dates:
                    return True
            except ValueError:
                return True
        remaining = DATE_RE.sub("", text).casefold()
        allowed = set(facts.numbers)
        if facts.rating_scale:
            allowed.update((Decimal(0), Decimal(10)))
        for match in NUMERAL_RE.finditer(remaining):
            if Decimal(match.group().rstrip("%").replace(",", "")) not in allowed:
                return True
        # Treat a compound as a single value; allowing 20 and 1 cannot authorize 21.
        for match in re.finditer(
            r"\btwenty[ -]+(one|two|three|four|five|six|seven|eight|nine)\b", remaining
        ):
            unit = 1 if match[1] == "one" else NUMBER_WORDS[match[1]]
            if Decimal(20 + unit) not in allowed:
                return True
        remaining = re.sub(
            r"\btwenty[ -]+(?:one|two|three|four|five|six|seven|eight|nine)\b", "", remaining
        )
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
        if facts.kind in {"verdict", "protocol"} and facts.phase is None:
            return True  # Historical phase comparisons are not today's instructions.
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

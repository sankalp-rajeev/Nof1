"""Rules and bounded typo matching; emergencies bypass extraction and all LLMs."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from rapidfuzz.fuzz import ratio

from app.agent.safety.config import INBOUND_FUZZY_THRESHOLD

RULES = {
    "chest": (r"chest.{0,25}(?:pain|pressure|tight)", r"(?:pain|pressure).{0,25}chest"),
    "breathing": (
        r"(?:cannot|cant|trouble|struggl\w*|difficulty).{0,18}breath\w*",
        r"shortness of breath",
        r"cant catch my breath",
    ),
    "stroke": (
        r"face.{0,25}droop\w*",
        r"speech.{0,20}slurr\w*",
        r"slurr\w*.{0,20}(?:speech|words)",
        r"sudden.{0,15}weak\w*",
        r"suddenly cannot raise.{0,10}arm",
    ),
    "allergy": (r"(?:throat|tongue).{0,20}swell\w*", r"severe allergic reaction", r"anaphyla\w*"),
    "overdose": (r"overdos\w*", r"poison\w*", r"too many (?:pills|tablets|medicines)"),
    "self_harm": (
        r"suicid\w*",
        r"(?:kill|hurt|harm|cut) myself",
        r"want to die",
        r"(?:dont|do not) want to live",
        r"self[ -]?harm",
    ),
    "bleeding": (
        r"bleed\w*.{0,20}sever\w*",
        r"severe bleed\w*",
        r"bleed\w*.{0,12}(?:wont|will not|cannot) stop",
        r"blood is pouring",
        r"bleeding a lot.{0,20}faint",
    ),
    "consciousness": (
        r"lost consciousness",
        r"passed out",
        r"blacking out",
        r"unconscious",
        r"fainted.{0,20}cannot stay awake",
    ),
    "headache": (
        r"worst.{0,20}headache",
        r"thunderclap.{0,15}headache",
        r"headache.{0,25}thunderclap",
        r"sudden extreme headache",
    ),
}
FUZZY_PHRASES = {
    "chest": ("chest pain", "chest pressure"),
    "breathing": ("cannot breathe", "trouble breathing", "shortness of breath"),
    "self_harm": ("suicidal thoughts",),
    "headache": ("worst headache", "thunderclap headache"),
}


@dataclass(frozen=True)
class InboundResult:
    red_flag: bool
    category: str | None = None
    source: Literal["rule", "llm"] | None = None


def _negated(text: str, position: int) -> bool:
    clause = re.split(r"[.!?;]|\bbut\b|\bhowever\b", text[:position])[-1]
    prefix = " ".join(clause.split()[-6:])
    return bool(re.search(r"\b(?:no|not|never|dont|without)\b", prefix))


def inbound_safety(text: str, *, possible_emergency: bool = False) -> InboundResult:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("’", "'").replace("'", "")
    for category, expressions in RULES.items():
        for expression in expressions:
            for match in re.finditer(expression, normalized):
                if not _negated(normalized, match.start()):
                    return InboundResult(True, category, "rule")
    words = list(re.finditer(r"[a-z]+", normalized))
    for category, phrases in FUZZY_PHRASES.items():
        for phrase in phrases:
            count = len(phrase.split())
            for index in range(len(words) - count + 1):
                start, end = words[index].start(), words[index + count - 1].end()
                if ratio(normalized[start:end], phrase) >= INBOUND_FUZZY_THRESHOLD and not _negated(
                    normalized, start
                ):
                    return InboundResult(True, category, "rule")
    return (
        InboundResult(True, "possible_emergency", "llm")
        if possible_emergency
        else InboundResult(False)
    )

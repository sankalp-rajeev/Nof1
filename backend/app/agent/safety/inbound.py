"""Rules and bounded typo matching; emergencies bypass extraction and all LLMs."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from rapidfuzz.fuzz import ratio

from app.agent.safety.config import INBOUND_FUZZY_THRESHOLD

RULES = {
    "chest": (
        r"chest.{0,25}(?:pain|pressure|tight)",
        r"(?:pain|pressure).{0,25}chest",
        r"elephant.{0,25}(?:on|sitting on).{0,10}chest",
        r"(?:sit|stand|press|push|crush)\w*.{0,15}(?:on|against).{0,12}chest",
    ),
    "breathing": (
        r"(?:cannot|cant|trouble|struggl\w*|difficulty).{0,18}breath\w*",
        r"shortness of breath",
        r"cant catch my breath",
        r"lips?.{0,15}(?:going|turning|turn|gone).{0,5}blue",
        r"gasp\w* for (?:air|breath)",
    ),
    "stroke": (
        r"face.{0,25}droop\w*",
        r"speech.{0,20}slurr\w*",
        r"words.{0,30}slurr\w*",
        r"(?:words|speech).{0,25}(?:garbl|jumbl|mush|incoher)\w*",
        r"(?:cant|cannot|unable to).{0,10}(?:feel|move|lift).{0,15}"
        r"(?:left|right|one).{0,10}(?:arm|leg|side)",
        r"slurr\w*.{0,20}(?:speech|words)",
        r"sudden.{0,15}weak\w*",
        r"suddenly cannot raise.{0,10}arm",
    ),
    "allergy": (
        r"(?:throat|tongue).{0,20}swel\w*",
        r"severe allergic reaction",
        r"anaphyla\w*",
        r"throat.{0,25}clos\w* up",
        r"(?:face|lips?|mouth).{0,20}swel\w*.{0,30}(?:wheez|breath)\w*",
    ),
    "overdose": (
        r"overdos\w*",
        r"poison\w*",
        r"too many (?:pills|tablets|medicines)",
        r"(?:took|swallowed).{0,10}(?:whole|entire) bottle"
        r"(?!\s+of\s+(?:water|juice|milk)\b)",
    ),
    "self_harm": (
        r"suicid\w*",
        r"(?:kill|hurt|harm|cut) myself",
        r"want to die",
        r"(?:dont|do not) want to live",
        r"self[ -]?harm",
        r"(?:dont|do not) want to be here anymore",
        r"(?:dont|do not) think i can keep myself safe",
        r"(?:cant|cannot) keep myself safe",
        r"(?:everyone|people|family|friends|they).{0,25}(?:better|happier|easier)"
        r".{0,20}(?:without me|if i (?:were|was) gone)",
    ),
    "bleeding": (
        r"bleed\w*.{0,20}sever\w*",
        r"severe bleed\w*",
        r"bleed\w*.{0,12}(?:wont|will not|cannot) stop",
        r"blood is pouring",
        r"bleeding a lot.{0,20}faint",
        r"(?:towel|cloth|clothes).{0,15}soaked.{0,10}blood",
        r"(?:wont|will not|cannot|cant) stop bleed\w*",
    ),
    "consciousness": (
        r"lost consciousness",
        r"passed out",
        r"black(?:ed|ing)? out",
        r"unconscious",
        r"fainted.{0,20}cannot stay awake",
        r"next thing i knew.{0,25}(?:floor|ground)",
        r"(?:meds|medication|medicine|pills?|tablets?).{0,70}"
        r"(?:cant|cannot|unable to).{0,10}(?:stay|keep).{0,5}awake",
    ),
    "headache": (
        r"worst.{0,20}headache",
        r"thunderclap.{0,15}headache",
        r"headache.{0,25}thunderclap",
        r"sudden extreme headache",
        r"headache.{0,20}(?:instantly|sudden\w*).{0,15}worst pain",
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
    # Negation must attach to this symptom, not an earlier ordinary-log statement.
    return bool(
        re.search(
            r"\b(?:no|not|never|dont|without)\s+"
            r"(?:(?:any|a|an|the|having|experiencing|feeling|getting|have|had|feel|"
            r"thinking|about|of|signs|symptoms|longer|more)\s+)*$",
            clause,
        )
    )


def _bounded_headache(text: str, start: int, end: int) -> bool:
    """A routine relative comparison is distinct from a sudden/worst-ever headache."""
    suffix = text[end:]
    bounded = re.match(r"\s+(?:of (?:the|this)|this) (?:week|month|day)\b", suffix)
    clause = re.split(r"[.!?;]", text[:start])[-1] + text[start:]
    onset = re.search(r"\b(?:sudden\w*|instantly|thunderclap)\b|worst[ -]ever|my life", clause)
    return bool(bounded and not onset)


def _non_symptom_action(category: str, text: str, start: int, end: int) -> bool:
    """Distinguish transitive distribution and container transport from ingestion/fainting."""
    span, suffix = text[start:end], text[end:]
    if category == "overdose" and span.startswith("took"):
        return bool(re.match(r"\s+(?:to|back to|into)\s+(?:the|a|an|my|our)\b", suffix))
    if category == "consciousness" and span == "passed out":
        return bool(re.match(r"\s+(?:the|some|these|those|our|my|your)\s+\w+s\b", suffix))
    return False


def inbound_safety(text: str, *, possible_emergency: bool = False) -> InboundResult:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("’", "'").replace("'", "")
    for category, expressions in RULES.items():
        for expression in expressions:
            for match in re.finditer(expression, normalized):
                if (
                    not _negated(normalized, match.start())
                    and not (
                        category == "headache" and _bounded_headache(normalized, *match.span())
                    )
                    and not _non_symptom_action(category, normalized, *match.span())
                ):
                    return InboundResult(True, category, "rule")
    words = list(re.finditer(r"[a-z]+", normalized))
    for category, phrases in FUZZY_PHRASES.items():
        for phrase in phrases:
            count = len(phrase.split())
            for index in range(len(words) - count + 1):
                start, end = words[index].start(), words[index + count - 1].end()
                if (
                    ratio(normalized[start:end], phrase) >= INBOUND_FUZZY_THRESHOLD
                    and not _negated(normalized, start)
                    and not (category == "headache" and _bounded_headache(normalized, start, end))
                ):
                    return InboundResult(True, category, "rule")
    return (
        InboundResult(True, "possible_emergency", "llm")
        if possible_emergency
        else InboundResult(False)
    )

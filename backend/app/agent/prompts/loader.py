"""Load only checked-in prompt names and reject missing template variables."""

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, Field, JsonValue

from app.agent.llm.base import LLMMessage

PROMPT_NAMES = (
    "turn_analyzer",
    "composer_checkin",
    "composer_insight",
    "composer_experiment",
    "composer_answer",
    "persona_render",
    "judge_safety",
)


class PromptHeader(BaseModel):
    version: int = Field(ge=1, strict=True)


@dataclass(frozen=True)
class Prompt:
    text: str
    version: int

    def messages(self, payload: dict[str, JsonValue]) -> tuple[LLMMessage, ...]:
        return (
            LLMMessage("system", self.text),
            LLMMessage("user", json.dumps(payload, ensure_ascii=True, sort_keys=True)),
        )


def load_prompt(name: str) -> Prompt:
    if name not in PROMPT_NAMES:
        raise ValueError("Unknown prompt name")
    source = (Path(__file__).parent / f"{name}.md").read_text(encoding="utf-8")
    if not source.startswith("---\n"):
        raise ValueError("Prompt requires version frontmatter")
    header, separator, body = source[4:].partition("\n---\n")
    if not separator:
        raise ValueError("Unclosed prompt frontmatter")
    version = PromptHeader.model_validate(yaml.safe_load(header)).version
    text = (
        Environment(undefined=StrictUndefined, autoescape=False).from_string(body).render().strip()
    )
    if not text or "{{" in text or "{%" in text:
        raise ValueError("Prompt must be complete")
    return Prompt(text, version)

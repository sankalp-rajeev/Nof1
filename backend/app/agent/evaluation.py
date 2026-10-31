"""Offline E7 guard regression using only scripted FakeLLM responses."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter

from app.agent.composer import compose
from app.agent.llm.base import CallContext, LLMResponse
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.safety.output_guard import Facts, OutputGuard
from app.agent.safety.templates import MEDICAL_REFUSAL
from app.agent.tracing import MemoryTraceStore
from app.config import ROOT, Settings
from app.domain.schemas import DomainModel


class AdversarialCase(DomainModel):
    id: str
    user_text: str
    intent: Literal["checkin", "medical_ask"]
    unsafe_reply: str


def adversarial_cases(
    path: Path = ROOT / "evals/safety/adversarial_dx.jsonl",
) -> list[AdversarialCase]:
    return [
        AdversarialCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evaluate_e7() -> list[str]:
    issues: list[str] = []
    cases = adversarial_cases()
    if len(cases) < 25 or len({row.id for row in cases}) != len(cases):
        issues.append("E7 fixture count or identity failure")
    for index, case in enumerate(cases):
        facts = Facts()
        if case.intent == "medical_ask":
            reply = MEDICAL_REFUSAL
        else:
            encoded = TypeAdapter(dict[str, str]).dump_json({"reply": case.unsafe_reply}).decode()
            fake = FakeLLMClient([LLMResponse(encoded, 10, 5)] * 2)
            router = LLMRouter(
                Settings.model_construct(llm_composer="ollama:fixture"),
                store=MemoryTraceStore(),
                prices=PriceBook({}),
                clients={"ollama": fake},
            )
            result = compose(
                router,
                {},
                ctx=CallContext("composer_checkin", "synthetic", None, UUID(int=index + 1)),
            )
            reply, facts = result.text, result.facts
        if {"G1", "G2"} & set(OutputGuard().check(reply, facts)):
            issues.append(f"E7: {case.id}")
    return issues

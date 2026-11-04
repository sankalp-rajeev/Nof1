"""Synthetic-only provider tapes and offline extraction replay; no fixture retuning."""

import json
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.agent.analyzer import TurnAnalysis, analyze
from app.agent.llm.base import CallContext, LLMClient, LLMMessage, LLMResponse, ProviderError
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import request_key
from app.agent.llm.router import LLMRouter
from app.agent.tracing import MemoryTraceStore
from app.config import ROOT, Settings
from app.domain.normalize import normalize
from app.domain.schemas import DomainModel, ExposureChecklist, Pending, RateOutcome, SleepHours
from sim.extraction import ExtractionScore, Label, identity, score_extraction


class Attempt(DomainModel):
    key: str
    ctx: CallContext
    messages: tuple[LLMMessage, ...]
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    failed: bool = False
    http_status: int | None = None


class RecordingClient:
    def __init__(self, client: LLMClient, tape: list[Attempt]) -> None:
        self.client, self.tape = client, tape

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        if ctx.data_class != "synthetic":
            raise ValueError("Only synthetic calls may enter an evaluation tape")
        attempt = Attempt(
            key=request_key(messages, schema, max_tokens, temperature, ctx.purpose),
            ctx=ctx,
            messages=tuple(messages),
        )
        try:
            result = self.client.generate(
                messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
            )
        except ProviderError as error:
            self.tape.append(
                attempt.model_copy(update={"failed": True, "http_status": error.status_code})
            )
            raise
        self.tape.append(
            attempt.model_copy(
                update={
                    "text": result.text,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            )
        )
        return result


class RecordingRouter(LLMRouter):
    tape: list[Attempt]

    def _client(self, provider: str, model: str) -> LLMClient:
        client = super()._client(provider, model)
        if not isinstance(client, RecordingClient):
            client = RecordingClient(client, self.tape)
            self.clients[f"{provider}:{model}"] = client
        return client


class ReplayClient:
    def __init__(self, attempts: Sequence[Attempt]) -> None:
        self.attempts: dict[str, deque[Attempt]] = defaultdict(deque)
        for row in attempts:
            if row.ctx.data_class != "synthetic":
                raise ValueError("Replay requires synthetic calls")
            self.attempts[row.key].append(row)

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        if ctx.data_class != "synthetic":
            raise ValueError("Replay requires synthetic context")
        key = request_key(messages, schema, max_tokens, temperature, ctx.purpose)
        if not self.attempts[key]:
            raise ValueError("Replay request differs from the frozen fixture")
        row = self.attempts[key].popleft()
        if row.failed:
            raise ProviderError("recorded_failure", status_code=row.http_status)
        return LLMResponse(row.text, row.input_tokens, row.output_tokens)


class ReplayCase(DomainModel):
    id: str
    gold: tuple[Label, ...]
    text: str
    pending: Pending | None = None
    attempts: tuple[Attempt, ...] = ()
    expected: ExtractionScore


class ReplayBundle(DomainModel):
    version: Literal[1] = 1
    data_class: Literal["synthetic"] = "synthetic"
    provenance: Literal["handwritten_offline", "live_synthetic"]
    max_output_tokens: int = Field(default=800, gt=0)
    cases: tuple[ReplayCase, ...]
    expected: ExtractionScore


def analysis_labels(analysis: TurnAnalysis, pending: Pending | None) -> list[Label]:
    output = [
        Label.model_validate(event.model_dump(exclude={"time_of_day"})) for event in analysis.events
    ]
    # Separate materializations of one observation are one logical extraction.
    # Duplicate raw events remain duplicates and are scored as false positives.
    supplemental = [
        Label(kind="symptom", name=row.outcome, severity=row.value, relative_day=row.relative_day)
        for row in analysis.ratings
    ]
    if isinstance(pending, ExposureChecklist) and (
        analysis.checklist_yes or analysis.checklist_none
    ):
        yes = {normalize(name).canonical for name in analysis.checklist_yes}
        supplemental.extend(
            Label(
                kind=normalize(name).kind or "life",
                name=name,
                status="done" if normalize(name).canonical in yes else "skipped",
            )
            for name in pending.names
        )
    for event in supplemental:
        if not any(
            identity(event) == identity(other)
            and event.status == other.status
            and event.severity == other.severity
            for other in output
        ):
            output.append(event)
    return output


def fixed_labels(text: str, pending: Pending | None) -> list[Label]:
    if isinstance(pending, RateOutcome) and text.isdecimal() and 0 <= int(text) <= 10:
        return [Label(kind="symptom", name=pending.outcome, severity=int(text))]
    if isinstance(pending, SleepHours):
        try:
            value = float(text)
            if 0 <= value <= 16:
                return [Label(kind="sleep", name="sleep", value=value, unit="h")]
        except ValueError:
            pass
    if isinstance(pending, ExposureChecklist) and text.casefold() == "none":
        return [
            Label(kind=normalize(name).kind or "life", name=name, status="skipped")
            for name in pending.names
        ]
    return []


def replay_case(case: ReplayCase, max_output_tokens: int) -> ExtractionScore:
    if not case.attempts:
        predictions = fixed_labels(case.text, case.pending)
    else:
        client = ReplayClient(case.attempts)
        settings = Settings.model_construct(
            llm_analyzer="ollama:replay", max_output_tokens=max_output_tokens
        )
        router = LLMRouter(
            settings,
            store=MemoryTraceStore(),
            prices=PriceBook({}),
            clients={"ollama": client},
            sleep=lambda _: None,
        )
        try:
            result = analyze(
                router,
                case.attempts[0].messages,
                ctx=CallContext("analyzer", "synthetic", None, UUID(int=1)),
            )
            predictions = (
                analysis_labels(result.value, case.pending) if result.value is not None else []
            )
        except ProviderError:
            predictions = []
    return score_extraction(case.gold, predictions)


def replay_bundle(bundle: ReplayBundle) -> ExtractionScore:
    score = ExtractionScore()
    for case in bundle.cases:
        current = replay_case(case, bundle.max_output_tokens)
        if current != case.expected:
            raise ValueError(f"Extraction replay drift: {case.id}")
        score += current
    if score != bundle.expected:
        raise ValueError("Extraction replay aggregate drift")
    return score


def replay_regression(directory: Path = ROOT / "evals/fixtures/chat") -> list[str]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        return ["P8 replay fixtures are missing"]
    issues = []
    for path in paths:
        try:
            replay_bundle(ReplayBundle.model_validate_json(path.read_bytes()))
        except ValueError as error:
            issues.append(f"{path.name}: {error}")
    return issues


def score_dict(score: ExtractionScore) -> dict[str, int | float]:
    return {**asdict(score), "f1": score.f1}


def write_bundle(bundle: ReplayBundle, path: Path) -> None:
    if any(a.ctx.data_class != "synthetic" for case in bundle.cases for a in case.attempts):
        raise ValueError("Cannot record real data")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")

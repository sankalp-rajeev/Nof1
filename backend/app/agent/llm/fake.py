"""Scripted offline client. Recording fixtures is explicit and synthetic-only."""

import hashlib
import json
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import BaseModel, JsonValue, TypeAdapter

from app.agent.llm.base import CallContext, LLMMessage, LLMResponse


@dataclass(frozen=True)
class RecordedCall:
    key: str
    ctx: CallContext
    messages: tuple[LLMMessage, ...]
    schema: dict[str, JsonValue] | None = None


def request_key(
    messages: Sequence[LLMMessage],
    schema: type[BaseModel] | None,
    max_tokens: int,
    temperature: float,
    purpose: str,
) -> str:
    payload = {
        "purpose": purpose,
        "messages": [asdict(message) for message in messages],
        "schema": schema.model_json_schema() if schema else None,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class FakeLLMClient:
    def __init__(
        self,
        outputs: Sequence[LLMResponse] = (),
        *,
        replay: dict[str, list[LLMResponse]] | None = None,
    ) -> None:
        self._outputs = deque(outputs)
        self._replay = {key: deque(values) for key, values in replay.items()} if replay else {}
        self._is_replay = replay is not None
        self.calls: list[RecordedCall] = []
        self.recordings: dict[str, list[LLMResponse]] = {}

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        key = request_key(messages, schema, max_tokens, temperature, ctx.purpose)
        self.calls.append(
            RecordedCall(key, ctx, tuple(messages), schema.model_json_schema() if schema else None)
        )
        queue = self._replay.get(key, deque()) if self._is_replay else self._outputs
        if not queue:
            raise RuntimeError(
                f"FakeLLMClient script exhausted for purpose={ctx.purpose}, key={key}"
            )
        response = queue.popleft()
        self.recordings.setdefault(key, []).append(response)
        return response

    def save(self, path: Path) -> None:
        if any(call.ctx.data_class != "synthetic" for call in self.calls):
            raise ValueError("Only synthetic calls may be saved as replay fixtures")
        payload = {key: [asdict(item) for item in items] for key, items in self.recordings.items()}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_recording(cls, path: Path) -> "FakeLLMClient":
        recordings = TypeAdapter(dict[str, list[LLMResponse]]).validate_json(path.read_bytes())
        return cls(replay=recordings)

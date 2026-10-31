"""Bounded two-stage context from structured storage; user content is always data."""

import json
import math
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select

from app.agent.llm.base import LLMMessage
from app.agent.prompts.loader import load_prompt
from app.agent.tools.registry import EmptyArgs, InsightsArgs, TimelineArgs, ToolRegistry
from app.config import (
    BASE_CONTEXT_TOKENS,
    CONTEXT_MESSAGE_LIMIT,
    CONTEXT_NAME_LIMIT,
    PATH_CONTEXT_TOKENS,
    PATH_DAYS,
)
from app.db import models as m
from app.domain.schemas import PendingState


@dataclass(frozen=True)
class Context:
    payload: dict[str, JsonValue]
    messages: tuple[LLMMessage, ...]
    estimated_tokens: int


class ContextBuilder:
    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def base(self, state: PendingState, user_text: str, message_id: UUID) -> Context:
        repo, user_id = self.tools.repo, self.tools.user_id
        history: list[JsonValue] = []
        for row in repo.list_messages(user_id, limit=CONTEXT_MESSAGE_LIMIT + 1):
            if row.id != message_id:
                history.append({"role": row.role, "content": row.content})
        history = history[-CONTEXT_MESSAGE_LIMIT:]
        names: list[JsonValue] = list(
            repo.session.scalars(
                select(m.Event.name)
                .where(m.Event.user_id == user_id)
                .group_by(m.Event.name)
                .order_by(func.count().desc(), m.Event.name)
                .limit(CONTEXT_NAME_LIMIT)
            )
        )
        tracking = repo.get_tracking(user_id)
        experiment = self.tools.get_experiment_status(EmptyArgs())["experiment"]
        phase_context = (
            {key: experiment[key] for key in ("phase", "washout", "status")}
            if isinstance(experiment, dict)
            else None
        )
        payload: dict[str, JsonValue] = {
            "history": history,
            "top_names": names,
            "pending": state.model_dump(mode="json")["pending"],
            "tracking": tracking.model_dump(mode="json"),
            "today": self.tools.day.isoformat(),
            "experiment": phase_context,
            "user_text": user_text,
        }
        return self._fit(payload, "turn_analyzer", BASE_CONTEXT_TOKENS)

    def path(self, base: Context, intent: str) -> Context:
        payload = dict(base.payload)
        # Copy mutable truncation lists; the base snapshot remains intact.
        for key in ("history", "top_names"):
            value = payload[key]
            if isinstance(value, list):
                payload[key] = list(value)
        if intent == "ask_data":
            timeline = self.tools.query_timeline(
                TimelineArgs(
                    start=self.tools.day - timedelta(days=PATH_DAYS - 1), end=self.tools.day
                )
            )
            days = timeline["days"]
            assert isinstance(days, dict)
            payload["timeline"] = [{"date": key, "rows": value} for key, value in days.items()]
            payload["insights"] = self.tools.get_insights(InsightsArgs())["patterns"]
        elif intent == "experiment":
            payload["experiment"] = self.tools.get_experiment_status(EmptyArgs())["experiment"]
        return self._fit(payload, "composer_answer", PATH_CONTEXT_TOKENS)

    @staticmethod
    def _fit(payload: dict[str, JsonValue], prompt_name: str, budget: int) -> Context:
        prompt = load_prompt(prompt_name)

        def size() -> int:
            return math.ceil(
                sum(len(m.role) + len(m.content) for m in prompt.messages(payload)) / 4
            )

        for key in ("history", "top_names", "timeline"):
            items = payload.get(key)
            while isinstance(items, list) and items and size() > budget:
                items.pop(0)
        # Oversize current text is clipped only after the prescribed truncation sequence.
        while size() > budget:
            text = payload.get("user_text")
            if isinstance(text, str) and text:
                payload["user_text"] = text[: max(0, len(text) - (size() - budget) * 4 - 1)]
                payload["user_text_truncated"] = True
            else:
                # Bound large structured tool snapshots without retaining free text.
                for key in ("insights", "experiment"):
                    if payload.get(key):
                        payload[key] = None
                        break
                else:
                    results = payload.get("tool_results")
                    candidates = (
                        [
                            (len(json.dumps(value)), i)
                            for i, value in enumerate(results)
                            if isinstance(value, dict)
                            and "error" not in value
                            and value != {"truncated": True}
                        ]
                        if isinstance(results, list)
                        else []
                    )
                    if candidates and isinstance(results, list):
                        results[max(candidates)[1]] = {"truncated": True}
                    else:
                        raise ValueError("Required workflow context exceeds its token budget")
        return Context(payload, prompt.messages(payload), size())

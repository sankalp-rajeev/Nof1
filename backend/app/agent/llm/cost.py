"""Conservative preflight reservations with explicit prices and token fallbacks."""

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field

from app.agent.llm.base import CallContext, LLMMessage, PolicyError
from app.agent.tracing import CallTrace, TraceStore
from app.config import ROOT, Settings


class BudgetExceeded(RuntimeError):
    pass


class Price(BaseModel):
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)

    def __init__(self, input_per_million: Decimal, output_per_million: Decimal) -> None:
        super().__init__(input_per_million=input_per_million, output_per_million=output_per_million)

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            self.input_per_million * input_tokens + self.output_per_million * output_tokens
        ) / Decimal(1000000)


class PriceEntry(BaseModel):
    input: Decimal | None = Field(default=None, ge=0)
    output: Decimal | None = Field(default=None, ge=0)


class PriceBook:
    def __init__(self, prices: Mapping[str, Price]) -> None:
        self._prices = dict(prices)

    @classmethod
    def load(cls, path: Path = ROOT / "config" / "prices.yaml") -> "PriceBook":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("Prices must be a provider:model mapping")
        prices: dict[str, Price] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                raise ValueError("Price keys must be strings")
            entry = PriceEntry.model_validate(value)
            if entry.input is not None and entry.output is not None:
                prices[key] = Price(entry.input, entry.output)
        return cls(prices)

    def get(self, provider: str, model: str) -> Price | None:
        return self._prices.get(f"{provider}:{model}", self._prices.get(f"{provider}:*"))


def estimated_tokens(messages: Sequence[LLMMessage], schema: type[BaseModel] | None) -> int:
    import json

    count = sum(len(message.content) + len(message.role) for message in messages)
    if schema is not None:
        count += len(json.dumps(schema.model_json_schema(), sort_keys=True))
    return math.ceil(count / 4)


class CostTracker:
    def __init__(
        self,
        settings: Settings,
        *,
        store: TraceStore,
        prices: PriceBook,
        mode: Literal["app", "cli"],
        clock: Callable[[], datetime],
    ) -> None:
        self.settings, self.store, self.prices = settings, store, prices
        self.mode, self.clock = mode, clock
        self._cli_ids: set[UUID] = set()

    def reserve(
        self,
        ctx: CallContext,
        *,
        provider: str,
        model: str,
        prompt_version: int,
        input_estimate: int,
    ) -> CallTrace:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Budget clock must be timezone-aware")
        utc_start = datetime.combine(now.astimezone(UTC).date(), time(), UTC)
        price = self.prices.get(provider, model)
        error: str | None = None
        with self.store.transaction() as tx:
            user = tx.user(ctx.user_id) if ctx.user_id is not None else None
            if ctx.user_id is not None and user is None:
                raise PolicyError("User identity is required")
            actual_class = (
                "real"
                if user is not None and user.is_demo
                else user.data_class
                if user
                else "synthetic"
            )
            if ctx.data_class != actual_class or (
                provider == "deepseek" and actual_class != "synthetic"
            ):
                raise PolicyError("Provider/data-class policy denied this call")
            local_start = (
                datetime.combine(
                    now.astimezone(ZoneInfo(user.tz)).date(), time(), ZoneInfo(user.tz)
                )
                if user
                else utc_start
            )
            local_end = datetime.combine(
                local_start.date() + timedelta(days=1), time(), local_start.tzinfo
            )
            records = (
                tx.records(since=min(utc_start, local_start))
                if self.mode == "app"
                else tx.records(ids=self._cli_ids)
            )
            scope = (
                [
                    row
                    for row in records
                    if utc_start <= row.created_at < utc_start + timedelta(days=1)
                ]
                if self.mode == "app"
                else records
            )
            input_used = sum(
                row.input_tokens
                + row.output_tokens
                + row.reserved_input_tokens
                + row.reserved_output_tokens
                for row in scope
            )
            spend = sum(
                (
                    Decimal(str(value))
                    for row in scope
                    for value in (row.cost_usd, row.reserved_cost_usd)
                    if value is not None
                ),
                Decimal(0),
            )
            projected = (
                price.cost(input_estimate, self.settings.max_output_tokens) if price else None
            )
            if (
                input_used + input_estimate + self.settings.max_output_tokens
                > self.settings.max_total_tokens
            ):
                error = "total_tokens"
            elif projected is not None and spend + projected > Decimal(
                str(self.settings.max_spend_usd)
            ):
                error = "spend"
            elif (
                self.mode == "app"
                and user is not None
                and sum(
                    row.user_id == user.id
                    and local_start <= row.created_at < local_end
                    and row.status != "budget"
                    for row in records
                )
                >= self.settings.max_user_daily_llm_calls
            ):
                error = "user_daily_calls"
            # Attempt numbers continue across validation/regeneration calls in this trace.
            attempts = tx.records(since=None)
            attempt = 1 + max(
                (
                    row.attempt
                    for row in attempts
                    if row.trace_id == ctx.trace_id and row.purpose == ctx.purpose
                ),
                default=0,
            )
            row = CallTrace(
                id=uuid4(),
                trace_id=ctx.trace_id,
                user_id=ctx.user_id,
                purpose=ctx.purpose,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                data_class=actual_class,
                attempt=attempt,
                input_tokens=0,
                output_tokens=0,
                reserved_input_tokens=0 if error else input_estimate,
                reserved_output_tokens=0 if error else self.settings.max_output_tokens,
                reserved_cost_usd=float(projected) if not error and projected is not None else None,
                latency_ms=0,
                cost_usd=0 if price else None,
                status="budget" if error else "error",
                error=error or "reserved",
                created_at=now,
            )
            tx.put(row)
            if self.mode == "cli":
                self._cli_ids.add(row.id)
        if error:
            raise BudgetExceeded(error)
        return row

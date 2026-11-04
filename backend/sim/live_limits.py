"""Eval-only, durable global dispatch limits; never records message content."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock

from pydantic import BaseModel

from app.agent.llm.base import CallContext, LLMClient, LLMMessage, LLMResponse
from app.agent.llm.cost import BudgetExceeded, PriceBook
from sim.config import GEMINI_MAX_INPUT_TOKENS, LIVE_MAX_CALLS
from sim.replay import RecordingClient, RecordingRouter


def claim_run(directory: Path) -> None:
    """Exclusive directory claim survives errors; a consumed run cannot be resumed."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(exist_ok=False)
    (directory / "STARTED.json").write_text(
        json.dumps({"started_at": datetime.now(UTC).isoformat(), "rerun_allowed": False}),
        encoding="utf-8",
    )


class LiveLimits:
    def __init__(
        self,
        prices: PriceBook,
        path: Path,
        *,
        max_calls: int = LIVE_MAX_CALLS,
        cap: Decimal = Decimal("1.00"),
    ) -> None:
        if not 0 < max_calls <= LIVE_MAX_CALLS or not Decimal(0) < cap <= Decimal("1.00"):
            raise ValueError("Live limits must be positive and within authorized ceilings")
        self.prices, self.path, self.max_calls, self.cap = prices, path, max_calls, cap
        self.case_id = "preflight"
        self.rows: list[dict[str, object]] = []
        self.spent = Decimal(0)
        self.reserved = Decimal(0)
        self.stop_reason: str | None = None
        self.lock = RLock()
        self.save()

    def summary(self) -> dict[str, object]:
        uncertain = any(row["cost_usd"] is None for row in self.rows)
        return {
            "max_calls": self.max_calls,
            "spend_cap_usd": str(self.cap),
            "actual_calls": len(self.rows),
            "known_cost_usd": str(self.spent),
            "actual_cost_usd": None if uncertain else str(self.spent),
            "unsettled_upper_bound_usd": str(self.reserved),
            "accounted_upper_bound_usd": str(self.spent + self.reserved),
            "stop_reason": self.stop_reason,
            "attempts": self.rows,
        }

    def save(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.summary(), indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def refuse(self, reason: str) -> None:
        self.stop_reason = self.stop_reason or reason
        self.save()
        raise BudgetExceeded(self.stop_reason)

    def reserve(self, route: str, max_tokens: int, ctx: CallContext) -> tuple[int, Decimal]:
        with self.lock:
            if self.stop_reason is not None:
                self.refuse(self.stop_reason)
            if ctx.data_class != "synthetic":
                self.refuse("non_synthetic")
            if len(self.rows) >= self.max_calls:
                self.refuse("call_cap")
            provider, model = route.split(":", 1)
            price = self.prices.get(provider, model)
            if price is None:
                self.refuse("missing_price")
            assert price is not None
            if provider == "ollama":
                if price.cost(1, 1) != 0:
                    self.refuse("unsupported_local_price")
                reserve = Decimal(0)
            elif route in GEMINI_MAX_INPUT_TOKENS:
                if datetime.now(UTC).date().isoformat() > "2026-12-31":
                    self.refuse("expired_price")
                reserve = price.cost(GEMINI_MAX_INPUT_TOKENS[route], max_tokens)
            else:
                self.refuse("unbounded_model")
            if self.spent + self.reserved + reserve > self.cap:
                self.refuse("spend_admission_cap")
            self.rows.append(
                {
                    "attempt": len(self.rows) + 1,
                    "case_id": self.case_id,
                    "purpose": ctx.purpose,
                    "route": route,
                    "status": "dispatched",
                    "reserved_usd": str(reserve),
                    "cost_usd": "0" if provider == "ollama" else None,
                }
            )
            self.reserved += reserve
            self.save()  # Persist before dispatch, including every transport retry.
            return len(self.rows) - 1, reserve

    def settle(self, index: int, reserve: Decimal, result: LLMResponse | None) -> None:
        with self.lock:
            row = self.rows[index]
            if (
                reserve
                and result is not None
                and (result.input_tokens <= 0 or result.output_tokens <= 0)
            ):
                # The production adapter can represent missing output usage as zero.
                # A returned paid generation without complete usage stays unsettled.
                result = None
            if result is None:
                row["status"] = "provider_error"
                # Missing usage is never assumed free. Keep its full reservation.
            else:
                provider, model = str(row["route"]).split(":", 1)
                price = self.prices.get(provider, model)
                assert price is not None
                cost = price.cost(result.input_tokens, result.output_tokens)
                self.reserved -= reserve
                self.spent += cost
                row.update(
                    status="returned",
                    cost_usd=str(cost),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
                if cost > reserve or self.spent + self.reserved >= self.cap:
                    # Provider usage exceeding its documented bounds is retained as evidence.
                    self.stop_reason = "spend_cap"
            self.save()


class LimitedClient:
    def __init__(self, client: LLMClient, limits: LiveLimits, route: str) -> None:
        self.client, self.limits, self.route = client, limits, route

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        index, reserve = self.limits.reserve(self.route, max_tokens, ctx)
        try:
            result = self.client.generate(
                messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
            )
        except BaseException:
            self.limits.settle(index, reserve, None)
            raise
        self.limits.settle(index, reserve, result)
        return result


class LimitedRouter(RecordingRouter):
    limits: LiveLimits

    def _client(self, provider: str, model: str) -> LLMClient:
        client = super()._client(provider, model)
        assert isinstance(client, RecordingClient)
        if not isinstance(client.client, LimitedClient):
            client.client = LimitedClient(client.client, self.limits, f"{provider}:{model}")
        return client

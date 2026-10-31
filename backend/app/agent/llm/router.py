"""The single policy/budget/trace/retry boundary for every provider attempt."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from time import sleep as time_sleep
from typing import Literal

from google import genai
from google.genai import types
from openai import OpenAI
from pydantic import BaseModel
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.agent.llm.base import (
    CallContext,
    LLMClient,
    LLMMessage,
    LLMResponse,
    PolicyError,
    ProviderError,
)
from app.agent.llm.cost import CostTracker, PriceBook, estimated_tokens
from app.agent.llm.gemini import GeminiClient
from app.agent.llm.openai_compat import OpenAICompatClient
from app.agent.prompts.loader import load_prompt
from app.agent.tracing import TraceStore
from app.config import Settings
from app.logging import protect_provider_logs

PURPOSES = {
    "analyzer": ("llm_analyzer", "turn_analyzer"),
    "composer_checkin": ("llm_composer", "composer_checkin"),
    "composer_answer": ("llm_composer", "composer_answer"),
    "composer_experiment": ("llm_composer", "composer_experiment"),
    "composer_insight": ("llm_narrator", "composer_insight"),
    "persona": ("sim_persona", "persona_render"),
    "judge_safety": ("llm_narrator", "judge_safety"),
    "xcheck": ("sim_xcheck_extractor", "turn_analyzer"),
}


class RoutedClient:
    def __init__(self, router: "LLMRouter", purpose: str) -> None:
        self.router, self.purpose = router, purpose

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        if ctx.purpose != self.purpose:
            raise PolicyError("Call purpose must match the selected route")
        return self.router.generate(
            messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
        )


class LLMRouter:
    def __init__(
        self,
        settings: Settings,
        *,
        store: TraceStore,
        prices: PriceBook,
        clients: Mapping[str, LLMClient] | None = None,
        mode: Literal["app", "cli"] = "cli",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time_sleep,
    ) -> None:
        protect_provider_logs()
        self.settings, self.store, self.prices = settings, store, prices
        self.clients = dict(clients or {})
        self.mode, self.clock, self.sleep = mode, clock, sleep
        self.cost = CostTracker(settings, store=store, prices=prices, mode=mode, clock=clock)

    def get(self, purpose: str) -> LLMClient:
        if purpose not in PURPOSES:
            raise ValueError(f"Unknown LLM purpose: {purpose}")
        if self.mode == "app" and purpose in {"judge_safety", "persona", "xcheck"}:
            raise PolicyError("Evaluation-only purpose is unavailable in the app")
        route = str(getattr(self.settings, PURPOSES[purpose][0]))
        if "CHANGE_ME" in route:
            raise ValueError(f"Configure verified model for purpose={purpose}, id={route}")
        return RoutedClient(self, purpose)

    def _client(self, provider: str, model: str) -> LLMClient:
        key = f"{provider}:{model}"
        if key in self.clients:
            return self.clients[key]
        if provider in self.clients:
            return self.clients[provider]
        if provider == "gemini":
            if not self.settings.gemini_api_key.get_secret_value():
                raise ValueError("GEMINI_API_KEY is required")
            result: LLMClient = GeminiClient(
                genai.Client(
                    api_key=self.settings.gemini_api_key.get_secret_value(),
                    http_options=types.HttpOptions(
                        timeout=int(self.settings.llm_timeout_s * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ),
                model,
            )
        else:
            api_key = (
                self.settings.deepseek_api_key.get_secret_value()
                if provider == "deepseek"
                else "ollama"
            )
            if not api_key:
                raise ValueError("DEEPSEEK_API_KEY is required")
            endpoint = (
                "https://api.deepseek.com"
                if provider == "deepseek"
                else self.settings.ollama_base_url
            )
            result = OpenAICompatClient(
                OpenAI(
                    api_key=api_key,
                    base_url=endpoint,
                    max_retries=0,
                    timeout=self.settings.llm_timeout_s,
                ),
                model,
            )
        self.clients[key] = result
        return result

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float = 0,
        ctx: CallContext,
    ) -> LLMResponse:
        self.get(ctx.purpose)
        route_attr, prompt_name = PURPOSES[ctx.purpose]
        provider, model = str(getattr(self.settings, route_attr)).split(":", 1)
        version = load_prompt(prompt_name).version
        retry = Retrying(
            stop=stop_after_attempt(3),
            retry=retry_if_exception(
                lambda error: (
                    isinstance(error, ProviderError)
                    and error.status_code is not None
                    and (error.status_code == 429 or 500 <= error.status_code <= 599)
                )
            ),
            wait=wait_exponential(multiplier=0.25, max=1),
            sleep=self.sleep,
            reraise=True,
        )
        for attempt in retry:
            with attempt:
                row = self.cost.reserve(
                    ctx,
                    provider=provider,
                    model=model,
                    prompt_version=version,
                    input_estimate=estimated_tokens(messages, schema),
                )
                started = monotonic()
                try:
                    response = self._client(provider, model).generate(
                        messages,
                        schema=schema,
                        max_tokens=min(max_tokens, self.settings.max_output_tokens),
                        temperature=temperature,
                        ctx=ctx,
                    )
                except Exception as error:
                    code = error.code if isinstance(error, ProviderError) else "client_error"
                    with self.store.transaction() as tx:
                        tx.put(
                            row.model_copy(
                                update={
                                    "latency_ms": (monotonic() - started) * 1000,
                                    "status": "error",
                                    "error": code,
                                }
                            )
                        )
                    if isinstance(error, ProviderError):
                        raise ProviderError(
                            error.code,
                            status_code=error.status_code,
                            route=f"purpose={ctx.purpose}, id={provider}:{model}",
                        ) from None
                    raise
                price = self.prices.get(provider, model)
                cost = (
                    float(price.cost(response.input_tokens, response.output_tokens))
                    if price
                    else None
                )
                with self.store.transaction() as tx:
                    tx.put(
                        row.model_copy(
                            update={
                                "input_tokens": response.input_tokens,
                                "output_tokens": response.output_tokens,
                                "latency_ms": (monotonic() - started) * 1000,
                                "cost_usd": cost,
                                "status": "ok",
                                "error": None,
                            }
                        )
                    )
                return replace(response, call_id=row.id)
        raise RuntimeError("Retry loop did not produce a response")

    def mark_invalid(self, response: LLMResponse) -> None:
        if response.call_id is None:
            raise ValueError("Only routed responses can be marked invalid")
        with self.store.transaction() as tx:
            rows = tx.records(ids=[response.call_id])
            if len(rows) != 1:
                raise ValueError("Trace row missing")
            tx.put(rows[0].model_copy(update={"status": "invalid", "error": "schema_validation"}))

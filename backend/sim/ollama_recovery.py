"""Eval-only local persona recovery. Readiness never performs generation."""

from collections.abc import Callable, Sequence

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, Field, ValidationError

from app.agent.llm.base import CallContext, LLMClient, LLMMessage, LLMResponse, ProviderError
from app.agent.llm.router import LLMRouter
from app.agent.prompts.loader import load_prompt
from sim.config import E4_PERSONA_KEEP_ALIVE, E4_PERSONA_RETRY_WAITS_S, E4_READINESS_TIMEOUT_S
from sim.gpu_preflight import require_full_gpu
from sim.personas import persona_card
from sim.render import RenderedText


def ollama_ready(base_url: str) -> bool:
    """GET the model inventory, without loading a model or generating text."""
    try:
        with httpx.Client(timeout=E4_READINESS_TIMEOUT_S, trust_env=False) as client:
            return client.get(base_url.rstrip("/") + "/models").status_code == 200
    except httpx.HTTPError:
        return False


class NativeMessage(BaseModel):
    content: str = Field(min_length=1)


class NativeChatResponse(BaseModel):
    message: NativeMessage
    done: bool
    prompt_eval_count: int = Field(ge=0)
    eval_count: int = Field(ge=0)


class OllamaPersonaClient:
    """Native transport because Ollama 0.18.2 ignores keep_alive on /v1/chat/completions."""

    def __init__(self, client: OpenAI, model: str) -> None:
        self.client, self.model = client, model
        self.url = str(client.base_url).rstrip("/").removesuffix("/v1") + "/api/chat"

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        # Match the installed server's OpenAI-to-native mapping, including top_p=1.
        # Send the same JSON mode, not a new constrained-generation JSON schema.
        body: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": row.role, "content": row.content} for row in messages],
            "options": {"num_predict": max_tokens, "temperature": temperature, "top_p": 1.0},
            "stream": False,
            "keep_alive": E4_PERSONA_KEEP_ALIVE,
        }
        if schema is not None:
            body["format"] = "json"
        try:
            raw = self.client.post(self.url, body=body, cast_to=object)
        except APITimeoutError:
            raise ProviderError("timeout") from None
        except APIStatusError as error:
            raise ProviderError("provider_status", status_code=error.status_code) from None
        except APIConnectionError:
            raise ProviderError("connection") from None
        try:
            response = NativeChatResponse.model_validate(raw)
        except ValidationError:
            raise ProviderError("missing_content_or_usage") from None
        if not response.done:
            raise ProviderError("incomplete_response")
        return LLMResponse(
            response.message.content, response.prompt_eval_count, response.eval_count
        )


class SingleAttemptPersona:
    """Keep Ollama's outer recovery loop from nesting the router's HTTP retries."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        try:
            return self.client.generate(
                messages, schema=schema, max_tokens=max_tokens, temperature=temperature, ctx=ctx
            )
        except ProviderError as error:
            # The outer recovery loop owns all local-persona transport retries.
            # Suppress the generic 429/5xx retry predicate for this client only.
            raise ProviderError(error.code) from None


class PersonaRecovery:
    def __init__(self, ready: Callable[[], bool]) -> None:
        self.ready = ready
        self.readiness_checks = 0
        self.retry_dispatches = 0
        self.exhausted = False
        self.last_error: str | None = None

    def generate(
        self, dispatch: Callable[[], LLMResponse], sleep: Callable[[float], None]
    ) -> LLMResponse:
        try:
            return dispatch()
        except ProviderError as error:
            self.last_error = error.code
        # Four recovery slots, 180 seconds of deliberate waiting in total.
        # Offline readiness slots consume time but never consume a generation call.
        for delay in E4_PERSONA_RETRY_WAITS_S:
            sleep(delay)
            self.readiness_checks += 1
            if not self.ready():
                continue
            self.retry_dispatches += 1
            try:
                return dispatch()
            except ProviderError as error:
                self.last_error = error.code
        self.exhausted = True
        raise ProviderError("persona_retries_exhausted") from None


def warmup_persona(router: LLMRouter, ctx: CallContext) -> None:
    """Check response arrival and full GPU placement; discard unused warm-up content."""
    if not router.settings.sim_persona.startswith("ollama:"):
        raise ProviderError("persona_warmup_requires_local_ollama")
    router.get("persona").generate(
        load_prompt("persona_render").messages(
            {"events": [], "persona": persona_card(0).model_dump(mode="json")}
        ),
        schema=RenderedText,
        max_tokens=router.settings.max_output_tokens,
        temperature=0,
        ctx=ctx,
    )
    require_full_gpu(router.settings.sim_persona.split(":", 1)[1])

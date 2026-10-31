"""Gemini SDK adapter with user messages separated from the system instruction."""

import json
from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.agent.llm.base import CallContext, LLMMessage, LLMResponse, ProviderError


class GeminiClient:
    def __init__(self, client: genai.Client, model: str) -> None:
        self.client, self.model = client, model

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int,
        temperature: float,
        ctx: CallContext,
    ) -> LLMResponse:
        system = "\n".join(message.content for message in messages if message.role == "system")
        # Google's grammar compiler rejects TurnAnalysis. Request JSON syntax only;
        # the same declared schema still guides generation and is validated in code.
        plain_json = schema is not None and ctx.purpose == "analyzer"
        if plain_json:
            assert schema is not None
            system += "\nOutput JSON matching this schema: " + json.dumps(
                schema.model_json_schema()
            )
        contents = [
            types.Content(
                role="model" if message.role == "assistant" else "user",
                parts=[types.Part.from_text(text=message.content)],
            )
            for message in messages
            if message.role != "system"
        ]
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="application/json" if schema else None,
            response_json_schema=schema.model_json_schema() if schema and not plain_json else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except httpx.TimeoutException as error:
            raise ProviderError("timeout", exception_class=type(error).__name__) from None
        except errors.APIError as error:
            raise ProviderError(
                "provider_status",
                status_code=error.code,
                exception_class=type(error).__name__,
                google_status=error.status,
                provider_message=error.message,
            ) from None
        except httpx.RequestError as error:
            raise ProviderError("connection", exception_class=type(error).__name__) from None
        usage = response.usage_metadata
        if response.text is None or usage is None or usage.prompt_token_count is None:
            raise ProviderError("missing_content_or_usage")
        output = (
            max(0, (usage.total_token_count or 0) - usage.prompt_token_count)
            if usage.total_token_count is not None
            else (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        )
        return LLMResponse(response.text, usage.prompt_token_count, output)

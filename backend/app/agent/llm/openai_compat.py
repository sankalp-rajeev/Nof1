"""OpenAI SDK adapter for configured Ollama/DeepSeek endpoints; no internal retries."""

from collections.abc import Sequence
from typing import cast

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject, ResponseFormatText
from pydantic import BaseModel

from app.agent.llm.base import CallContext, LLMMessage, LLMResponse, ProviderError


class OpenAICompatClient:
    def __init__(self, client: OpenAI, model: str) -> None:
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
        payload = [
            cast(ChatCompletionMessageParam, {"role": message.role, "content": message.content})
            for message in messages
        ]
        response_format: ResponseFormatJSONObject | ResponseFormatText = (
            {"type": "json_object"} if schema is not None else {"type": "text"}
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=payload,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format,
            )
        except APITimeoutError:
            raise ProviderError("timeout") from None
        except APIStatusError as error:
            raise ProviderError("provider_status", status_code=error.status_code) from None
        except APIConnectionError:
            raise ProviderError("connection") from None
        if (
            not response.choices
            or response.choices[0].message.content is None
            or response.usage is None
        ):
            raise ProviderError("missing_content_or_usage")
        return LLMResponse(
            response.choices[0].message.content,
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
        )

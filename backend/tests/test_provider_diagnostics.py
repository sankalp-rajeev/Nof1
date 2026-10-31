import json
from uuid import UUID

import httpx
import pytest
from google import genai
from google.genai import types

from app.agent.analyzer import TurnAnalysis
from app.agent.llm.base import CallContext, LLMMessage, ProviderError
from app.agent.llm.cost import PriceBook
from app.agent.llm.diagnostics import safe_error
from app.agent.llm.gemini import GeminiClient
from app.agent.llm.router import LLMRouter
from app.agent.tracing import MemoryTraceStore
from app.config import Settings

pytestmark = pytest.mark.p6


def test_provider_error_records_real_fields_without_user_text_or_key() -> None:
    error = ProviderError(
        "provider_status",
        status_code=400,
        exception_class="ClientError",
        google_status="INVALID_ARGUMENT",
        provider_message=(
            "Invalid schema. Echo: private-health-canary brain fog. Credential sk-fixture-secret"
        ),
    )
    messages = [LLMMessage("user", '{"user_text":"private-health-canary brain fog"}')]
    result = safe_error(error, messages, ["sk-fixture-secret"])
    assert result.startswith("ClientError | HTTP 400 | Google INVALID_ARGUMENT | ")
    for part in ("private-health-canary", "brain", "fog", "sk-fixture-secret"):
        assert part not in result


def test_error_is_bounded_and_unknown_exceptions_never_log_their_message() -> None:
    error = ProviderError(
        "provider_status",
        status_code=400,
        exception_class="ClientError",
        google_status="INVALID_ARGUMENT",
        provider_message="schema " * 100,
    )
    assert len(safe_error(error, [])) <= 300
    assert "private-health-canary" not in safe_error(RuntimeError("private-health-canary"), [])


def test_analyzer_requests_json_without_google_grammar_but_validates_full_schema() -> None:
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": '{"intent":"checkin"}'}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 12,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 17,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with genai.Client(
            api_key="fixture", http_options=types.HttpOptions(httpx_client=http)
        ) as sdk:
            result = GeminiClient(sdk, "fixture").generate(
                [LLMMessage("system", "Extract."), LLMMessage("user", "private-health-canary")],
                schema=TurnAnalysis,
                max_tokens=800,
                temperature=0,
                ctx=CallContext("analyzer", "synthetic", None, UUID(int=960)),
            )
    config = captured[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert "responseJsonSchema" not in config and "responseSchema" not in config
    assert "TurnAnalysis" in json.dumps(captured[0]["systemInstruction"])
    assert "private-health-canary" not in json.dumps(captured[0]["systemInstruction"])
    assert TurnAnalysis.model_validate_json(result.text).intent == "checkin"


def test_failed_provider_has_zero_actual_usage_and_preserves_reservation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": "Invalid schema private-health-canary",
                }
            },
        )

    store = MemoryTraceStore()
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with genai.Client(
            api_key="fixture", http_options=types.HttpOptions(httpx_client=http)
        ) as sdk:
            router = LLMRouter(
                Settings(_env_file=None, llm_analyzer="gemini:fixture"),
                store=store,
                prices=PriceBook({}),
                clients={"gemini": GeminiClient(sdk, "fixture")},
            )
            with pytest.raises(ProviderError):
                router.generate(
                    [LLMMessage("user", "private-health-canary")],
                    max_tokens=800,
                    ctx=CallContext("analyzer", "synthetic", None, UUID(int=961)),
                )
    row = store.rows[0]
    assert row.input_tokens == row.output_tokens == 0
    assert row.reserved_input_tokens > 0 and row.reserved_output_tokens == 800
    assert row.error is not None and "HTTP 400 | Google INVALID_ARGUMENT" in row.error
    assert "private-health-canary" not in row.model_dump_json()

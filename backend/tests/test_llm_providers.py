import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from google import genai
from google.genai import types
from openai import OpenAI

from app.agent.llm.base import CallContext, LLMMessage, ProviderError
from app.agent.llm.cost import PriceBook
from app.agent.llm.gemini import GeminiClient
from app.agent.llm.openai_compat import OpenAICompatClient
from app.agent.llm.router import LLMRouter
from app.agent.tracing import MemoryTraceStore
from app.config import Settings

pytestmark = pytest.mark.p4
CTX = CallContext("analyzer", "synthetic", None, UUID(int=970))
MESSAGES = [
    LLMMessage("system", "Extract JSON."),
    LLMMessage("user", "private synthetic health note"),
]


def router_for(provider: str, client: object, store: MemoryTraceStore) -> LLMRouter:
    return LLMRouter(
        Settings(_env_file=None, llm_analyzer=f"{provider}:fixture", max_output_tokens=20),
        store=store,
        prices=PriceBook({}),
        clients={provider: client},
        sleep=lambda seconds: None,
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize("statuses,expected", [([429, 500, 200], 3), ([401], 1), ([408], 1)])
def test_openai_compatible_retries_only_429_and_5xx_and_traces_each_attempt(
    statuses: list[int], expected: int
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = statuses[len(requests) - 1]
        if status != 200:
            return httpx.Response(
                status,
                json={"error": {"message": "private synthetic health note", "type": "fixture"}},
            )
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": "fixture",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler), timeout=2) as http:
        sdk = OpenAI(
            api_key="fixture",
            base_url="http://provider.test/v1",
            http_client=http,
            max_retries=0,
            timeout=2,
        )
        store = MemoryTraceStore()
        router = router_for("ollama", OpenAICompatClient(sdk, "fixture"), store)
        if statuses[-1] == 200:
            result = router.get("analyzer").generate(
                MESSAGES, max_tokens=20, temperature=0, ctx=CTX
            )
            assert result.input_tokens == 7 and result.output_tokens == 2
        else:
            with pytest.raises(ProviderError):
                router.get("analyzer").generate(MESSAGES, max_tokens=20, temperature=0, ctx=CTX)
    assert len(requests) == len(store.rows) == expected
    assert [row.attempt for row in store.rows] == list(range(1, expected + 1))
    assert all("private synthetic health note" not in row.model_dump_json() for row in store.rows)


def test_provider_timeout_is_not_retried_and_body_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.extensions["timeout"]["read"] == 2
        raise httpx.ReadTimeout("private synthetic health note", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), timeout=2) as http:
        sdk = OpenAI(
            api_key="fixture",
            base_url="http://provider.test/v1",
            http_client=http,
            max_retries=0,
            timeout=2,
        )
        store = MemoryTraceStore()
        router = router_for("ollama", OpenAICompatClient(sdk, "fixture"), store)
        with pytest.raises(ProviderError, match="timeout"):
            router.get("analyzer").generate(MESSAGES, max_tokens=20, temperature=0, ctx=CTX)
    assert len(requests) == 1 and store.rows[0].status == "error"
    assert "private synthetic health note" not in caplog.text


def test_gemini_structured_request_keeps_system_and_user_separate_and_counts_usage() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "{}"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 9,
                    "candidatesTokenCount": 2,
                    "thoughtsTokenCount": 1,
                    "totalTokenCount": 12,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        sdk = genai.Client(
            api_key="fixture",
            http_options=types.HttpOptions(
                httpx_client=http, timeout=2000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        store = MemoryTraceStore()
        router = router_for("gemini", GeminiClient(sdk, "fixture"), store)
        response = router.get("analyzer").generate(MESSAGES, max_tokens=20, temperature=0, ctx=CTX)
        assert response.input_tokens == 9 and response.output_tokens == 3
        assert "private synthetic" not in json.dumps(captured[0].get("systemInstruction"))
        assert "private synthetic" in json.dumps(captured[0]["contents"])
        sdk.close()


def test_model_placeholder_fails_fast_with_purpose_and_id() -> None:
    router = LLMRouter(Settings(_env_file=None), store=MemoryTraceStore(), prices=PriceBook({}))
    with pytest.raises(ValueError, match="purpose=analyzer.*CHANGE_ME"):
        router.get("analyzer")


def test_unavailable_model_error_identifies_route_without_provider_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "private health text"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        sdk = OpenAI(
            api_key="fixture", base_url="http://provider.test/v1", http_client=http, max_retries=0
        )
        store = MemoryTraceStore()
        router = router_for("ollama", OpenAICompatClient(sdk, "fixture"), store)
        with pytest.raises(ProviderError, match="purpose=analyzer, id=ollama:fixture") as error:
            router.get("analyzer").generate(MESSAGES, max_tokens=20, temperature=0, ctx=CTX)
        assert "private health text" not in str(error.value)
        assert len(store.rows) == 1 and store.rows[0].status == "error"


def test_retry_attempts_reserve_tokens_and_stop_before_next_provider_call() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, json={"error": {"message": "fixture", "type": "rate_limit"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        sdk = OpenAI(
            api_key="fixture", base_url="http://provider.test/v1", http_client=http, max_retries=0
        )
        store = MemoryTraceStore()
        router = LLMRouter(
            Settings(
                _env_file=None,
                llm_analyzer="ollama:fixture",
                max_total_tokens=50,
                max_output_tokens=20,
            ),
            store=store,
            prices=PriceBook({}),
            clients={"ollama": OpenAICompatClient(sdk, "fixture")},
            sleep=lambda seconds: None,
        )
        from app.agent.llm.cost import BudgetExceeded

        with pytest.raises(BudgetExceeded):
            router.get("analyzer").generate(MESSAGES, max_tokens=20, temperature=0, ctx=CTX)
        assert len(requests) == 1 and [row.status for row in store.rows] == ["error", "budget"]


@pytest.mark.parametrize("timeout", [False, True])
def test_gemini_router_retries_statuses_but_not_timeouts(timeout: bool) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if timeout:
            raise httpx.ReadTimeout("private synthetic health note", request=request)
        status = 429 if len(requests) == 1 else 500
        return httpx.Response(
            status,
            json={"error": {"code": status, "message": "private synthetic health note"}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        sdk = genai.Client(
            api_key="fixture",
            http_options=types.HttpOptions(
                httpx_client=http, timeout=2000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        store = MemoryTraceStore()
        router = router_for("gemini", GeminiClient(sdk, "fixture"), store)
        with pytest.raises(ProviderError) as error:
            router.get("analyzer").generate(MESSAGES, max_tokens=20, temperature=0, ctx=CTX)
        assert "private synthetic health note" not in str(error.value)
        assert len(requests) == len(store.rows) == (1 if timeout else 3)
        assert all(row.status == "error" for row in store.rows)
        sdk.close()

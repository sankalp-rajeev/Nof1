from uuid import UUID

import pytest

from app import dev_chat
from app.agent.orchestrator import ChatResult
from app.config import Settings

pytestmark = pytest.mark.p5


def configured(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "app_env": "dev",
            "llm_analyzer": "gemini:fixture",
            "llm_composer": "gemini:fixture",
            "llm_narrator": "gemini:fixture",
            "gemini_api_key": "fixture",
            **overrides,
        },
    )


@pytest.mark.parametrize("environment", ["test", "prod"])
def test_chat_refuses_non_dev_before_database_or_provider_access(environment: str) -> None:
    with pytest.raises(ValueError, match="APP_ENV=dev"):
        dev_chat.validate_settings(configured(app_env=environment))


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url": "postgresql+psycopg://u:p@remote.invalid/db"},
        {"database_url": "postgresql+psycopg://u:p@localhost/nof1_test"},
        {"llm_analyzer": "gemini:CHANGE_ME"},
        {"llm_composer": "deepseek:fixture"},
        {"gemini_api_key": ""},
    ],
)
def test_chat_refuses_unsafe_or_unconfigured_targets(overrides: dict) -> None:
    with pytest.raises(ValueError):
        dev_chat.validate_settings(configured(**overrides))


def test_chat_forwards_lines_and_prints_replies_without_logging_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    user_id = UUID(int=9001)
    trace_id = UUID(int=9002)
    seen = []

    class Chat:
        def begin(self, user: UUID) -> ChatResult:
            assert user == user_id
            return ChatResult("First question.", trace_id)

        def process(self, user: UUID, line: str) -> ChatResult:
            assert user == user_id
            seen.append(line)
            return ChatResult("Synthetic reply.", trace_id)

    lines = iter(["", "private-repl-canary", "/quit"])
    output = []
    monkeypatch.setattr(dev_chat, "trace_metadata", lambda engine, result: {"llm_calls": []})
    dev_chat.repl(None, Chat(), user_id, read=lambda prompt: next(lines), write=output.append)
    assert seen == ["private-repl-canary"] and "Synthetic reply." in output
    assert "private-repl-canary" not in caplog.text


def test_temporary_user_cleanup_runs_when_the_session_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    session = MagicMock()
    monkeypatch.setattr(dev_chat, "Session", lambda engine: session)
    repository = MagicMock()
    repository.create_user.return_value.id = UUID(int=9003)
    monkeypatch.setattr(dev_chat, "Repository", lambda session: repository)
    with pytest.raises(RuntimeError, match="fixture"):
        with dev_chat.temporary_user(None) as user_id:
            raise RuntimeError("fixture")
    assert repository.create_user.call_args.args[0].data_class == "synthetic"
    repository.delete_user.assert_called_once_with(user_id)

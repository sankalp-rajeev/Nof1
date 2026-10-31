"""Manual dev-only terminal chat. Replies go to the terminal, never application logs."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.llm.cost import PriceBook
from app.agent.llm.router import LLMRouter
from app.agent.orchestrator import ChatResult, Orchestrator
from app.agent.tracing import SQLTraceStore
from app.config import Settings
from app.db.models import LLMCall
from app.db.repos import Repository
from app.db.session import create_db_engine
from app.domain.schemas import UserInput


def validate_settings(settings: Settings) -> None:
    """Refuse non-dev environments and nonlocal databases before any I/O."""
    if settings.app_env != "dev":
        raise ValueError("make chat requires APP_ENV=dev")
    database = make_url(settings.database_url)
    if database.host not in {"localhost", "127.0.0.1", "::1"} or not database.database:
        raise ValueError("make chat requires a local PostgreSQL database")
    if database.database.endswith("_test"):
        raise ValueError("make chat must not use the test database")
    for purpose, route in (
        ("analyzer", settings.llm_analyzer),
        ("composer", settings.llm_composer),
        ("narrator", settings.llm_narrator),
    ):
        if not route.startswith("gemini:") or "CHANGE_ME" in route:
            raise ValueError(f"Configure a verified Gemini model for {purpose} in .env")
    if not settings.gemini_api_key.get_secret_value():
        raise ValueError("GEMINI_API_KEY is required")


@contextmanager
def temporary_user(engine: Engine) -> Iterator[UUID]:
    """Create one synthetic local user; cascade-delete its rows on every normal exit."""
    with Session(engine) as session, session.begin():
        user_id = Repository(session).create_user(UserInput(data_class="synthetic")).id
    try:
        yield user_id
    finally:
        with Session(engine) as session, session.begin():
            Repository(session).delete_user(user_id)


def trace_metadata(engine: Engine, result: ChatResult) -> dict[str, JsonValue]:
    """Read content-free usage from persisted llm_calls before throwaway-user cleanup."""
    with Session(engine) as session:
        rows = session.scalars(
            select(LLMCall)
            .where(LLMCall.trace_id == result.trace_id)
            .order_by(LLMCall.created_at, LLMCall.purpose, LLMCall.attempt)
        )
        calls: list[JsonValue] = [
            {
                "id": str(row.id),
                "purpose": row.purpose,
                "model": row.model,
                "attempt": row.attempt,
                "status": row.status,
                "error": row.error,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "usage_estimated": row.status == "error",
                "cost_usd": row.cost_usd,
            }
            for row in rows
        ]
    return {
        "trace_id": str(result.trace_id),
        "analyzer_calls": result.analyzer_calls,
        "tool_calls": result.tool_calls,
        "regenerated": result.regenerated,
        "fallback": result.fallback,
        "limited": result.limited,
        "llm_calls": calls,
    }


def repl(
    engine: Engine,
    chat: Orchestrator,
    user_id: UUID,
    *,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> None:
    write(f"Temporary synthetic user: {user_id}. EOF, Ctrl-C, or /quit ends the session.")
    write(chat.begin(user_id).reply)
    while True:
        try:
            line = read("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() == "/quit":
            break
        if not line.strip():
            continue
        result = chat.process(user_id, line)
        write(result.reply)
        write(json.dumps(trace_metadata(engine, result), sort_keys=True))


def main() -> int:
    try:
        settings = Settings()
    except ValidationError:
        print("Invalid configuration; check .env and environment overrides.")
        return 1
    try:
        validate_settings(settings)
    except ValueError as error:
        print(str(error))
        return 1
    engine = create_db_engine(settings.database_url)
    try:
        with temporary_user(engine) as user_id:
            router = LLMRouter(
                settings, store=SQLTraceStore(engine), prices=PriceBook.load(), mode="cli"
            )
            repl(engine, Orchestrator(engine, router), user_id)
    except KeyboardInterrupt:
        return 0
    except SQLAlchemyError:
        print("Local database unavailable or schema outdated; run make db-up and make migrate.")
        return 1
    except Exception as error:
        # Exceptions may contain provider/user text; display only the exception type.
        print(f"Chat stopped ({type(error).__name__}); check local session cleanup.")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

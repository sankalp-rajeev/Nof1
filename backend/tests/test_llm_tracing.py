from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from app.agent.llm.base import CallContext, LLMMessage, LLMResponse, PolicyError
from app.agent.llm.cost import BudgetExceeded, PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.tracing import SQLTraceStore
from app.config import Settings
from app.db.repos import Repository
from app.db.session import create_db_engine, session_scope
from app.domain.schemas import UserInput

pytestmark = pytest.mark.p4
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
USER = UUID(int=980)
CTX = CallContext("analyzer", "synthetic", USER, UUID(int=981))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    engine = create_db_engine(Settings().database_url_test)
    assert engine.url.database is not None and engine.url.database.endswith("_test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        assert not inspect(connection).get_table_names()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            connection.execute(text("DROP TABLE alembic_version"))
        engine.dispose()


def test_sql_attempt_rows_and_cross_router_global_budget(engine: Engine) -> None:
    with session_scope(engine) as session:
        Repository(session).create_user(UserInput(data_class="synthetic"), user_id=USER)
    store = SQLTraceStore(engine)
    settings = Settings(
        _env_file=None, llm_analyzer="ollama:fixture", max_total_tokens=60, max_output_tokens=20
    )
    fake = FakeLLMClient([LLMResponse("{}", 30, 15)])
    first = LLMRouter(
        settings,
        store=store,
        prices=PriceBook({}),
        clients={"ollama": fake},
        mode="app",
        clock=lambda: NOW,
    )
    response = first.get("analyzer").generate(
        [LLMMessage("user", "synthetic note")], max_tokens=20, temperature=0, ctx=CTX
    )
    second = LLMRouter(
        settings,
        store=store,
        prices=PriceBook({}),
        clients={"ollama": FakeLLMClient([])},
        mode="app",
        clock=lambda: NOW,
    )
    with pytest.raises(BudgetExceeded):
        second.get("analyzer").generate(
            [LLMMessage("user", "synthetic note")], max_tokens=20, temperature=0, ctx=CTX
        )
    with store.transaction() as tx:
        rows = tx.records()
    assert len(rows) == 2
    assert rows[0].id == response.call_id
    assert (
        rows[0].input_tokens,
        rows[0].output_tokens,
        rows[0].data_class,
        rows[0].prompt_version,
        rows[0].status,
    ) == (30, 15, "synthetic", 1, "ok")
    assert rows[0].latency_ms >= 0 and rows[1].status == "budget"
    assert all("synthetic note" not in row.model_dump_json() for row in rows)
    with session_scope(engine) as session:
        Repository(session).delete_user(USER)


def test_sql_identity_prevents_forged_synthetic_context_for_real_demo(engine: Engine) -> None:
    with session_scope(engine) as session:
        Repository(session).create_user(UserInput(is_demo=True), user_id=USER)
    fake = FakeLLMClient([LLMResponse("{}", 1, 1)])
    router = LLMRouter(
        Settings(_env_file=None, llm_analyzer="deepseek:fixture"),
        store=SQLTraceStore(engine),
        prices=PriceBook({}),
        clients={"deepseek": fake},
        clock=lambda: NOW,
    )
    with pytest.raises(PolicyError):
        router.get("analyzer").generate(
            [LLMMessage("user", "synthetic note")], max_tokens=20, temperature=0, ctx=CTX
        )
    assert fake.calls == []
    with session_scope(engine) as session:
        Repository(session).delete_user(USER)

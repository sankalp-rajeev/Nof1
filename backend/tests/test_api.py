from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_chat import engine

from app.agent.experiment_manager import ExperimentManager
from app.agent.llm.base import LLMResponse
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.tracing import SQLTraceStore
from app.api.demo import advance_demo, load_demo
from app.config import Settings
from app.db import models as m
from app.db.repos import Repository
from app.domain.schemas import UserInput
from app.main import create_app

pytestmark = pytest.mark.p7
__all__ = ["engine"]
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        debug=False,
        llm_analyzer="ollama:fixture",
        llm_composer="ollama:fixture",
    )
    fake = FakeLLMClient(
        [
            LLMResponse('{"intent":"chitchat"}', 10, 5),
            LLMResponse('{"reply":"Thanks for the update."}', 10, 5),
        ]
    )
    router = LLMRouter(
        settings,
        store=SQLTraceStore(engine),
        prices=PriceBook({}),
        clients={"ollama": fake},
        mode="app",
        clock=lambda: NOW,
    )
    with TestClient(
        create_app(settings=settings, engine=engine, router=router, clock=lambda: NOW)
    ) as client:
        yield client
    with Session(engine) as session, session.begin():
        for user in session.scalars(select(m.User)):
            session.delete(user)


def load(client: TestClient) -> dict:
    response = client.post("/api/demo/load")
    assert response.status_code == 200, response.text
    return response.json()


def test_health_has_no_identity_and_identity_cookie_is_http_only(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert not client.cookies
    tracking = client.get("/api/tracking")
    assert tracking.status_code == 200
    assert "httponly" in tracking.headers["set-cookie"].lower()
    assert not tracking.json()["is_demo"]
    assert client.get("/api/messages").json() == []
    assert client.get("/api/insights").json() == []
    assert client.get("/api/experiments/current").json()["experiment"] is None


def test_demo_is_idempotent_and_exposes_planted_evidence_without_llm(
    client: TestClient, engine: Engine
) -> None:
    first = load(client)
    assert first["is_demo"] and first["today"] == "2026-02-14"
    assert client.get("/api/tracking").json()["clock_offset_days"] < 0
    insights = client.get("/api/insights").json()
    assert insights and any(row["effect"] < 0 and row["data_points"] for row in insights)
    assert load(client) == first
    timeline = client.get("/api/timeline?days=14").json()
    assert len(timeline["days"]) == 14
    with Session(engine) as session:
        assert not list(session.scalars(select(m.LLMCall)))


def test_demo_advances_to_verdict_with_no_llm(client: TestClient, engine: Engine) -> None:
    load(client)
    pattern = client.get("/api/insights").json()[0]
    proposal = client.post("/api/experiments", json={"pattern_id": pattern["id"]})
    assert proposal.status_code == 200, proposal.text
    experiment = proposal.json()["experiment"]
    accepted = client.post(f"/api/experiments/{experiment['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["experiment"]["started_on"] == "2026-02-15"
    step = client.post("/api/demo/advance", json={"days": 1})
    assert step.status_code == 200, step.text
    current = client.get("/api/experiments/current").json()
    assert current["today_plan"]["phase"] == "baseline"
    assert current["today"] == "2026-02-15"
    end = client.post("/api/demo/advance", json={"days": 13})
    assert end.status_code == 200, end.text
    current = client.get("/api/experiments/current").json()
    assert current["experiment"]["status"] == "completed"
    assert current["experiment"]["verdict"]["label"] in {
        "helped",
        "no_detectable_effect",
        "inconclusive",
        "worsened",
    }
    with Session(engine) as session:
        assert not list(session.scalars(select(m.LLMCall)))


def test_days_upsert_validation_terminal_and_user_scope(client: TestClient, engine: Engine) -> None:
    load(client)
    pattern = client.get("/api/insights").json()[0]
    experiment = client.post("/api/experiments", json={"pattern_id": pattern["id"]}).json()[
        "experiment"
    ]
    id = experiment["id"]
    client.post(f"/api/experiments/{id}/accept")
    future = f"/api/experiments/{id}/days/2026-02-15"
    assert client.put(future, json={"adherence": True, "outcome_value": 6}).status_code == 422
    assert (
        client.put(f"/api/experiments/{id}/days/2026-01-01", json={"adherence": True}).status_code
        == 422
    )
    client.post("/api/demo/advance", json={"days": 1})
    first = client.put(future, json={"adherence": False, "outcome_value": 6})
    assert first.status_code == 200, first.text
    second = client.put(future, json={"adherence": True, "outcome_value": 5})
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]
    assert client.put(future, json={"adherence": True, "outcome_value": 11}).status_code == 422
    assert client.put(future, json={"adherence": "true"}).status_code == 422
    client.post("/api/demo/advance", json={"days": 13})
    before = client.get("/api/experiments/current").json()["experiment"]["verdict"]
    assert client.put(future, json={"adherence": False}).status_code == 409
    assert client.get("/api/experiments/current").json()["experiment"]["verdict"] == before
    client.cookies.clear()
    assert client.put(future, json={"adherence": True}).status_code == 404


def test_non_demo_refusals_chat_idempotency_and_delete(client: TestClient, engine: Engine) -> None:
    assert client.post("/api/demo/advance", json={"days": 1}).status_code == 403
    id = str(uuid4())
    first = client.post(
        "/api/chat",
        json={"message": "ordinary synthetic hello", "tz": "America/New_York", "client_msg_id": id},
    )
    assert first.status_code == 200, first.text
    again = client.post(
        "/api/chat",
        json={"message": "ordinary synthetic hello", "tz": "America/New_York", "client_msg_id": id},
    )
    assert again.json() == first.json()
    assert len(client.get("/api/messages").json()) == 2
    assert client.post("/api/demo/load").status_code == 409
    assert client.get("/api/debug/llm_calls").status_code == 404
    uid = UUID(client.cookies["nof1_uid"])
    assert client.delete("/api/me").status_code == 200
    assert "nof1_uid" not in client.cookies
    with Session(engine) as session:
        assert session.get(m.User, uid) is None
        assert not list(session.scalars(select(m.Message).where(m.Message.user_id == uid)))


def test_uniform_errors_cors_and_rate_limit(client: TestClient) -> None:
    error = client.post("/api/chat", json={"message": "", "tz": "invalid"})
    assert error.status_code == 422 and set(error.json()) == {"error"}
    allowed = client.options(
        "/api/chat",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = client.options(
        "/api/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in denied.headers
    result = None
    for _ in range(31):
        result = client.get("/api/tracking")
    assert result is not None and result.status_code == 429
    assert result.json()["error"]["code"] == "rate_limit"


def test_demo_advance_is_chunk_invariant(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        repo = Repository(session)
        user = repo.create_user(UserInput(data_class="real"), user_id=UUID(int=7010))
        load_demo(repo, user.id, lambda: NOW)
        manager = ExperimentManager(repo, user.id, clock=lambda: NOW)
        pattern = session.scalar(
            select(m.Pattern).where(m.Pattern.user_id == user.id).order_by(m.Pattern.p_adj)
        )
        assert pattern is not None
        experiment = manager.propose(pattern_id=pattern.id, experiment_id=UUID(int=7011))
        manager.respond(experiment.id, "accept", confirmed=True)
        savepoint = session.begin_nested()
        advance_demo(repo, user.id, 14, lambda: NOW)
        bulk = experiment.verdict
        bulk_date = manager.day()
        bulk_ratings = [
            (r.local_date, r.value)
            for r in repo.list_ratings(user.id, experiment.started_on, manager.day())
        ]
        savepoint.rollback()
        session.expire_all()
        for _ in range(14):
            advance_demo(repo, user.id, 1, lambda: NOW)
        assert manager.day() == bulk_date
        assert experiment.verdict == bulk
        assert [
            (r.local_date, r.value)
            for r in repo.list_ratings(user.id, experiment.started_on, manager.day())
        ] == bulk_ratings
        repo.delete_user(user.id)


def test_red_flag_chat_never_calls_the_llm_and_error_inputs_are_scoped(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "chest pain since lunch", "tz": "UTC"})
    assert response.status_code == 200 and response.json()["safety"]["red_flag"]
    assert response.json()["events_logged"] == []
    assert client.get("/api/messages").json()[-1]["red_flag"]
    assert client.post("/api/demo/advance", json={"days": 15}).status_code == 422
    assert client.post("/api/experiments", json={"exposure": "antihistamine"}).status_code == 400

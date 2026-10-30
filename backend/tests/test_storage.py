from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import models
from app.db.repos import Repository
from app.db.session import create_db_engine, session_scope
from app.domain.schemas import EventInput, MessageInput, PendingState, UserInput

pytestmark = pytest.mark.p1
DAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
USER = UUID(int=101)
TRACE = UUID(int=102)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    db = create_db_engine(Settings().database_url_test)
    assert db.url.database is not None and db.url.database.endswith("_test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with db.begin() as connection:
        assert not inspect(connection).get_table_names(), "Test database must start empty"
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield db
    with db.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
        connection.execute(text("DROP TABLE alembic_version"))
    db.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def make_user(db: Session) -> models.User:
    return Repository(db).create_user(UserInput(tz="America/New_York"), user_id=USER)


def test_migration_creates_every_domain_table(engine: Engine) -> None:
    expected = {
        "users",
        "messages",
        "conversation_state",
        "tracked_outcomes",
        "tracked_exposures",
        "checkins",
        "events",
        "outcome_ratings",
        "patterns",
        "experiments",
        "experiment_days",
        "llm_calls",
        "safety_events",
    }
    assert set(inspect(engine).get_table_names()) - {"alembic_version"} == expected
    assert set(models.Base.metadata.tables) == expected


@pytest.mark.parametrize(
    "values",
    [
        {"kind": "meal", "severity": 4},
        {"kind": "symptom", "severity": -1},
        {"kind": "symptom", "severity": 11},
        {"kind": "symptom", "status": "skipped"},
        {"kind": "sleep", "status": "skipped"},
    ],
)
def test_database_enforces_event_constraints(db: Session, values: dict[str, object]) -> None:
    make_user(db)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            models.Event(
                user_id=USER,
                ts=NOW,
                local_date=DAY,
                name="synthetic",
                raw_name="synthetic",
                confidence=1,
                source="chat",
                **values,
            )
        )
        db.flush()


@pytest.mark.parametrize("table", ["checkins", "ratings", "experiment_days", "messages"])
def test_database_enforces_unique_keys(db: Session, table: str) -> None:
    make_user(db)
    repo = Repository(db)
    if table == "checkins":
        rows = [models.Checkin(user_id=USER, local_date=DAY) for _ in range(2)]
    elif table == "ratings":
        rows = [
            models.OutcomeRating(user_id=USER, local_date=DAY, outcome_name="fatigue", value=4)
            for _ in range(2)
        ]
    elif table == "messages":
        rows = [
            models.Message(
                user_id=USER,
                role="user",
                content="synthetic",
                trace_id=TRACE,
                client_msg_id=UUID(int=103),
            )
            for _ in range(2)
        ]
    else:
        experiment = repo.add_experiment(
            USER, exposure="walk", outcome="fatigue", protocol={}, seed=7
        )
        rows = [
            models.ExperimentDay(experiment_id=experiment.id, date=DAY, phase="on")
            for _ in range(2)
        ]
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add_all(rows)
        db.flush()


def test_repository_crud_and_latest_event_wins(db: Session) -> None:
    user = make_user(db)
    repo = Repository(db)
    assert repo.get_user(USER) is user
    assert user.data_class == "real"
    message = repo.add_message(
        USER,
        MessageInput(
            role="user", content="synthetic note", trace_id=TRACE, client_msg_id=UUID(int=104)
        ),
    )
    assert repo.find_message(USER, UUID(int=104)) is message
    assert repo.list_messages(USER) == [message]
    repo.set_tracking(
        USER, outcomes=[("fatigue", "lower")], exposures=["magnesium"], track_sleep=True
    )
    assert repo.get_tracking(USER).outcomes[0].name == "fatigue"
    assert repo.get_tracking(USER).exposures[0].name == "magnesium"
    assert user.track_sleep
    state = PendingState.model_validate({"pending": {"type": "rate_outcome", "outcome": "fatigue"}})
    repo.save_state(USER, state)
    assert repo.get_state(USER) == state
    checkin = repo.upsert_checkin(USER, DAY, completed=True, checklist_answered=True)
    assert (
        repo.upsert_checkin(USER, DAY, completed=False, checklist_answered=False).id == checkin.id
    )
    rating = repo.upsert_rating(USER, DAY, "fatigue", 3)
    assert repo.upsert_rating(USER, DAY, "fatigue", 6).id == rating.id
    assert repo.list_ratings(USER, DAY, DAY)[0].value == 6
    first = repo.add_event(
        USER,
        EventInput(kind="med", name="magnesium"),
        ts=NOW,
        local_date=DAY,
        message_id=message.id,
        created_at=NOW,
    )
    correction = repo.add_event(
        USER,
        EventInput(kind="med", name="magnesium", status="skipped"),
        ts=NOW,
        local_date=DAY,
        created_at=NOW + timedelta(seconds=1),
    )
    assert repo.latest_events(USER, DAY, DAY) == [correction]
    assert repo.list_events(USER, DAY, DAY) == [first, correction]
    assert repo.delete_user(USER)
    assert repo.get_user(USER) is None


def test_user_isolation_and_message_ownership(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    other = repo.create_user(UserInput(), user_id=UUID(int=201))
    message = repo.add_message(USER, MessageInput(role="user", content="synthetic", trace_id=TRACE))
    assert repo.list_messages(other.id) == []
    assert repo.latest_events(other.id, DAY, DAY) == []
    with pytest.raises(ValueError, match="message"):
        repo.add_event(
            other.id,
            EventInput(kind="life", name="walk"),
            ts=NOW,
            local_date=DAY,
            message_id=message.id,
        )


def test_user_delete_cascades_to_every_table(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    message = repo.add_message(USER, MessageInput(role="user", content="synthetic", trace_id=TRACE))
    repo.save_state(USER, PendingState())
    repo.set_tracking(USER, outcomes=[("fatigue", "lower")], exposures=["walk"])
    repo.upsert_checkin(USER, DAY)
    repo.upsert_rating(USER, DAY, "fatigue", 4)
    repo.add_event(USER, EventInput(kind="life", name="walk"), ts=NOW, local_date=DAY)
    pattern = models.Pattern(
        user_id=USER,
        run_id=UUID(int=105),
        pattern_key="walk|fatigue|0",
        exposure="walk",
        outcome="fatigue",
        lag_days=0,
        effect=-2,
        p_raw=0.01,
        p_adj=0.03,
        tier="weak",
        n_pairs=20,
        n_exposed=10,
        n_unexposed=10,
        window_start=DAY,
        window_end=DAY,
        data_points=[],
    )
    db.add(pattern)
    db.flush()
    experiment = repo.add_experiment(
        USER, exposure="walk", outcome="fatigue", protocol={}, seed=7, pattern_id=pattern.id
    )
    db.add(models.ExperimentDay(experiment_id=experiment.id, date=DAY, phase="baseline"))
    db.add(
        models.LLMCall(
            user_id=USER,
            trace_id=TRACE,
            purpose="analyzer",
            provider="fake",
            model="fake",
            prompt_version=1,
            data_class="real",
            attempt=1,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            status="ok",
        )
    )
    db.add(
        models.SafetyEvent(user_id=USER, message_id=message.id, category="synthetic", source="rule")
    )
    db.flush()
    repo.delete_user(USER)
    for table in models.Base.metadata.sorted_tables:
        assert db.execute(select(table)).all() == [], table.name


def test_session_scope_rolls_back_on_error(engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="rollback"):
        with session_scope(engine) as session:
            Repository(session).create_user(UserInput(), user_id=UUID(int=301))
            raise RuntimeError("rollback")
    with session_scope(engine) as session:
        assert Repository(session).get_user(UUID(int=301)) is None


def test_tracking_limits_validate_before_any_mutation(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    original = repo.set_tracking(USER, outcomes=[("fatigue", "lower")], exposures=["walk"])
    with pytest.raises(ValueError):
        repo.set_tracking(
            USER,
            outcomes=[("fatigue", "higher")],
            exposures=[
                "walk",
                "coffee",
                "dairy",
                "sugar",
                "alcohol",
                "magnesium",
            ],
        )
    assert repo.get_tracking(USER) == original
    with pytest.raises(ValueError, match="Duplicate"):
        repo.set_tracking(USER, exposures=["mag", "magnesium"])
    assert repo.get_tracking(USER) == original


def test_tracking_replacement_preserves_existing_history(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    repo.set_tracking(USER, outcomes=[("fatigue", "lower")], exposures=["walk", "coffee"])
    walk = db.scalar(select(models.TrackedExposure).where(models.TrackedExposure.name == "walk"))
    assert walk is not None
    initial_id = walk.id
    repo.set_tracking(USER, exposures=["coffee"])
    assert walk.active is False
    repo.set_tracking(USER, exposures=["walk"])
    assert walk.active is True and walk.id == initial_id
    assert len(list(db.scalars(select(models.TrackedExposure)))) == 2


def test_same_client_id_is_scoped_to_user_and_nulls_are_allowed(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    other = repo.create_user(UserInput(), user_id=UUID(int=401))
    data = MessageInput(
        role="user", content="synthetic", trace_id=TRACE, client_msg_id=UUID(int=402)
    )
    first = repo.add_message(USER, data)
    second = repo.add_message(other.id, data)
    assert first.id != second.id
    for _ in range(2):
        repo.add_message(USER, MessageInput(role="assistant", content="saved", trace_id=TRACE))
    assert len(repo.list_messages(USER)) == 3


def test_checkin_partial_updates_preserve_other_flags(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    repo.upsert_checkin(USER, DAY, completed=True, checklist_answered=True)
    updated = repo.upsert_checkin(USER, DAY, completed=False)
    assert not updated.completed and updated.checklist_answered
    unchanged = repo.upsert_checkin(USER, DAY)
    assert unchanged.id == updated.id and unchanged.checklist_answered


def test_latest_event_resolution_is_scoped_and_ties_are_deterministic(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    first = repo.add_event(
        USER, EventInput(kind="life", name="walk"), ts=NOW, local_date=DAY, created_at=NOW
    )
    first.id = UUID(int=501)
    second = repo.add_event(
        USER,
        EventInput(kind="life", name="walk", status="skipped"),
        ts=NOW,
        local_date=DAY,
        created_at=NOW,
    )
    second.id = UUID(int=502)
    other = repo.create_user(UserInput(), user_id=UUID(int=503))
    repo.add_event(
        other.id,
        EventInput(kind="life", name="walk"),
        ts=NOW,
        local_date=DAY,
        created_at=NOW + timedelta(seconds=1),
    )
    db.flush()
    assert repo.latest_events(USER, DAY, DAY) == [second]
    assert repo.latest_events(USER, DAY + timedelta(days=1), DAY + timedelta(days=1)) == []


def test_delete_preserves_other_users_and_unattributed_llm_calls(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    other = repo.create_user(UserInput(), user_id=UUID(int=601))
    message = repo.add_message(
        other.id, MessageInput(role="user", content="synthetic", trace_id=TRACE)
    )
    call = models.LLMCall(
        trace_id=TRACE,
        purpose="eval",
        provider="fake",
        model="fake",
        prompt_version=1,
        data_class="synthetic",
        attempt=1,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        status="ok",
    )
    db.add(call)
    db.flush()
    repo.delete_user(USER)
    assert repo.get_user(other.id) is other
    assert repo.list_messages(other.id) == [message]
    assert db.get(models.LLMCall, call.id) is call


def test_event_timestamps_must_be_aware_and_match_local_date(db: Session) -> None:
    make_user(db)
    repo = Repository(db)
    data = EventInput(kind="life", name="walk")
    with pytest.raises(ValueError, match="aware"):
        repo.add_event(USER, data, ts=datetime(2026, 10, 1, 12), local_date=DAY)
    with pytest.raises(ValueError, match="local date"):
        repo.add_event(USER, data, ts=datetime(2026, 10, 1, 1, tzinfo=UTC), local_date=DAY)


def test_database_engine_rejects_remote_test_database() -> None:
    with pytest.raises(ValueError, match="local"):
        create_db_engine("postgresql+psycopg://nof1:nof1@example.com/nof1_test")

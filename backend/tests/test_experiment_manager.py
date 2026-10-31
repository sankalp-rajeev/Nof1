from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app.agent.experiment_composer import compose_instruction, compose_verdict
from app.agent.experiment_manager import PROTOCOL, ExperimentError, ExperimentManager
from app.agent.insights import InsightSurfacer
from app.agent.llm.base import CallContext, LLMResponse
from app.agent.llm.cost import PriceBook
from app.agent.llm.fake import FakeLLMClient
from app.agent.llm.router import LLMRouter
from app.agent.safety.output_guard import OutputGuard
from app.config import EXPERIMENT_LIMITATION, Settings
from app.db import models as m
from app.db.repos import Repository
from app.db.session import create_db_engine
from app.domain.schemas import EventInput, UserInput
from app.domain.timeutil import map_event_time
from app.stats.experiment import schedule

pytestmark = pytest.mark.p6
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
DAY = NOW.date()
USER = UUID(int=6001)


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


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def setup(db: Session) -> tuple[Repository, m.User, ExperimentManager]:
    repo = Repository(db)
    user = repo.create_user(UserInput(is_demo=True, data_class="synthetic"), user_id=USER)
    repo.set_tracking(
        USER, outcomes=[("fatigue", "lower")], exposures=["magnesium", "coffee", "antihistamine"]
    )
    for i in range(5):
        mapped = map_event_time(DAY, "UTC", relative_day=-i)
        for name in ("magnesium", "coffee", "antihistamine"):
            repo.add_event(
                USER,
                EventInput(kind="med" if name != "coffee" else "meal", name=name),
                ts=mapped.ts,
                local_date=mapped.local_date,
            )
    return repo, user, ExperimentManager(repo, USER, clock=lambda: NOW)


def accepted(db: Session) -> tuple[Repository, m.User, ExperimentManager, m.Experiment]:
    repo, user, manager = setup(db)
    row = manager.propose(exposure="magnesium", experiment_id=UUID(int=6002))
    manager.respond(row.id, "accept")
    return repo, user, manager, row


def test_lifecycle_dates_and_demo_clock_advance(db: Session) -> None:
    repo, user, manager, row = accepted(db)
    assert row.status == "accepted" and row.started_on == DAY + timedelta(days=1)
    plans = schedule(PROTOCOL.validate_python(row.protocol))
    assert plans[-1].date == row.started_on + timedelta(days=13)
    assert (
        len(
            list(db.scalars(select(m.ExperimentDay).where(m.ExperimentDay.experiment_id == row.id)))
        )
        == 14
    )
    user.clock_offset_days = 1
    assert manager.advance().status == "baseline"
    user.clock_offset_days = 3
    assert manager.advance().status == "running"
    user.clock_offset_days = 16
    assert manager.advance().status == "running"
    user.clock_offset_days = 17
    assert manager.advance().status == "completed"
    assert manager.evaluate(row.id)["label"] == "inconclusive"


def test_expiry_and_illegal_transitions_and_single_active(db: Session) -> None:
    repo, user, manager = setup(db)
    row = manager.propose(exposure="coffee")
    with pytest.raises(ExperimentError, match="already active"):
        manager.propose(exposure="magnesium")
    with pytest.raises(ExperimentError):
        manager.respond(row.id, "abandon")
    user.clock_offset_days = 2
    assert manager.advance().status == "proposed"
    user.clock_offset_days = 3
    assert manager.advance().status == "abandoned" and row.end_reason == "expired"
    with pytest.raises(ExperimentError):
        manager.respond(row.id, "accept", confirmed=True)
    replacement = manager.propose(exposure="coffee")
    assert replacement.id != row.id


@pytest.mark.parametrize(
    "name", ["antihistamine", "short_sleep", "unknown exposure", "prescription medication"]
)
def test_ineligible_exposures_return_reason_and_clinician_message(db: Session, name: str) -> None:
    _, _, manager = setup(db)
    with pytest.raises(ExperimentError) as error:
        manager.propose(exposure=name)
    assert error.value.code and error.value.status_code == 400 and "clinician" in str(error.value)


def test_corrections_reduce_done_day_eligibility(db: Session) -> None:
    repo, user, manager = setup(db)
    mapped = map_event_time(DAY, "UTC")
    repo.add_event(
        USER,
        EventInput(kind="med", name="magnesium", status="skipped"),
        ts=mapped.ts,
        local_date=DAY,
    )
    with pytest.raises(ExperimentError) as error:
        manager.propose(exposure="magnesium")
    assert error.value.code == "insufficient_exposure"


def test_late_entry_before_completion_counts_then_snapshot_is_frozen(db: Session) -> None:
    repo, user, manager, row = accepted(db)
    plans = schedule(PROTOCOL.validate_python(row.protocol))
    user.clock_offset_days = 15
    analysis = [p for p in plans if p.analysis]
    for plan in analysis[:-1]:
        manager.record_day(row.id, plan.date, True, outcome_value=1 if plan.phase == "on" else 6)
    assert row.status == "running"
    manager.record_day(
        row.id, analysis[-1].date, True, outcome_value=1 if analysis[-1].phase == "on" else 6
    )
    assert row.status == "completed"
    verdict = manager.evaluate(row.id)
    assert verdict["label"] == "helped" and verdict["n_on"] == verdict["n_off"] == 4
    with pytest.raises(ExperimentError) as error:
        manager.record_day(row.id, analysis[0].date, False, outcome_value=10)
    assert error.value.status_code == 409
    repo.upsert_rating(USER, analysis[0].date, "fatigue", 10)
    assert manager.evaluate(row.id) == verdict


def test_complete_on_last_analysis_day_before_grace_when_all_filled(db: Session) -> None:
    repo, user, manager, row = accepted(db)
    plans = schedule(PROTOCOL.validate_python(row.protocol))
    for plan in plans:
        user.clock_offset_days = (plan.date - DAY).days
        if plan.analysis:
            manager.record_day(
                row.id, plan.date, True, outcome_value=2 if plan.phase == "on" else 5
            )
    assert row.status == "completed" and row.ended_on == plans[-1].date


def test_future_and_other_user_writes_are_rejected_and_abandon_needs_confirmation(
    db: Session,
) -> None:
    repo, user, manager, row = accepted(db)
    with pytest.raises(ExperimentError) as error:
        manager.record_day(row.id, DAY + timedelta(days=1), True)
    assert error.value.code == "future_day"
    with pytest.raises(ExperimentError):
        manager.respond(row.id, "accept", confirmed=True)
    with pytest.raises(ExperimentError):
        manager.respond(row.id, "abandon")
    manager.request_abandon(row.id)
    assert row.status == "accepted"
    manager.respond(row.id, "abandon")
    assert row.status == "abandoned" and row.end_reason == "user"
    with pytest.raises(ExperimentError):
        manager.record_day(row.id, DAY, True)


def router_for(reply: str) -> LLMRouter:
    import json

    return LLMRouter(
        Settings(_env_file=None, llm_composer="ollama:fixture", llm_narrator="ollama:fixture"),
        store=__import__("app.agent.tracing", fromlist=["MemoryTraceStore"]).MemoryTraceStore(),
        prices=PriceBook({}),
        clients={"ollama": FakeLLMClient([LLMResponse(json.dumps({"reply": reply}), 10, 5)])},
    )


def test_all_fourteen_daily_instructions_follow_phase_and_washout(db: Session) -> None:
    repo, user, manager, row = accepted(db)
    for plan in schedule(PROTOCOL.validate_python(row.protocol)):
        user.clock_offset_days = (plan.date - DAY).days
        text = f"{plan.phase.upper()}: " + (
            "Keep your usual routine." if plan.phase == "baseline" else "Follow your accepted plan."
        )
        if plan.washout:
            text += " This day is not counted."
        result = compose_instruction(
            router_for(text),
            row,
            manager,
            CallContext("composer_experiment", "synthetic", None, UUID(int=6100)),
        )
        assert not OutputGuard().check(result.text, result.facts)
        assert result.facts.phase == plan.phase and result.facts.washout == plan.washout


def test_verdict_narration_keeps_counts_and_limitation(db: Session) -> None:
    repo, user, manager, row = accepted(db)
    user.clock_offset_days = 17
    manager.advance()
    result = compose_verdict(
        router_for("The result is inconclusive."),
        row,
        CallContext("composer_experiment", "synthetic", None, UUID(int=6101)),
    )
    assert "0 ON days and 0 OFF days" in result.text and EXPERIMENT_LIMITATION in result.text
    assert not OutputGuard().check(result.text, result.facts)


def add_pattern(
    db: Session, *, effect: float = -2, tier: str = "weak", key: str = "coffee|fatigue|0"
) -> m.Pattern:
    row = m.Pattern(
        user_id=USER,
        run_id=uuid4(),
        pattern_key=key,
        exposure="coffee",
        outcome="fatigue",
        lag_days=0,
        effect=effect,
        p_raw=0.01,
        p_adj=0.03,
        tier=tier,
        n_pairs=30,
        n_exposed=15,
        n_unexposed=15,
        perm_mode="mc",
        n_valid=500,
        window_start=DAY - timedelta(days=30),
        window_end=DAY,
        data_points=[{"outcome_date": str(DAY), "exposure_date": str(DAY), "x": 1, "y": 4}],
    )
    db.add(row)
    db.flush()
    return row


def test_surfacing_identity_tier_sign_cooldown_and_frozen_evidence(db: Session) -> None:
    repo, user, manager = setup(db)
    surfacer = InsightSurfacer(repo, USER, clock=lambda: NOW)
    original = add_pattern(db)
    assert surfacer.surface().id == original.id
    snapshot = deepcopy(surfacer.snapshot(original.id))
    user.clock_offset_days = 3
    add_pattern(db)
    assert surfacer.surface() is None
    upgraded = add_pattern(db, tier="moderate")
    assert surfacer.surface().id == upgraded.id
    flipped = add_pattern(db, effect=2, tier="moderate")
    assert surfacer.surface() is None
    user.clock_offset_days = 6
    assert surfacer.surface().id == flipped.id
    repo.upsert_rating(USER, DAY, "fatigue", 10)
    assert surfacer.snapshot(original.id) == snapshot


def import_world(repo: Repository, user: m.User, world: object) -> None:
    from app.domain.normalize import normalize
    from sim.config import EXPOSURES

    repo.set_tracking(
        user.id, outcomes=[("fatigue", "lower")], exposures=list(EXPOSURES[:5]), track_sleep=True
    )
    for day in world.days:
        if not day.observed:
            continue
        mapped = map_event_time(day.date, "UTC")
        repo.upsert_checkin(user.id, day.date, completed=True, checklist_answered=True)
        repo.upsert_rating(user.id, day.date, "fatigue", int(day.y))
        for name, value in zip(EXPOSURES, day.reported_exposures, strict=True):
            repo.add_event(
                user.id,
                EventInput(
                    kind=normalize(name).kind or "life",
                    name=name,
                    status="done" if value else "skipped",
                    source="sim",
                ),
                ts=mapped.ts,
                local_date=day.date,
            )
        repo.add_event(
            user.id,
            EventInput(
                kind="sleep", name="sleep", value=day.sleep_hours, unit="hours", source="sim"
            ),
            ts=mapped.ts,
            local_date=day.date,
        )
    user.clock_offset_days = (world.days[-1].date - DAY).days
    repo.upsert_checkin(user.id, world.days[-1].date, completed=True)


def test_demo_seed_to_insight_to_fourteen_days_returns_helped(db: Session) -> None:
    from sim.demo import demo_world
    from sim.world import simulate_experiment

    repo, user, manager = setup(db)
    world = demo_world()
    import_world(repo, user, world)
    surfacer = InsightSurfacer(repo, USER, clock=lambda: NOW)
    run_id = surfacer.scan_if_needed()
    assert run_id is not None
    assert surfacer.scan_if_needed() is None
    pattern = surfacer.surface()
    assert pattern is not None and pattern.exposure == world.truth.effects[0].exposure
    row = manager.propose(pattern_id=pattern.id, experiment_id=UUID(int=6020))
    manager.respond(row.id, "accept")
    simulated = simulate_experiment(world, PROTOCOL.validate_python(row.protocol), 1.0)
    for observation in simulated.observations:
        user.clock_offset_days = (observation.date - DAY).days
        manager.record_day(
            row.id,
            observation.date,
            observation.adherence,
            outcome_value=int(observation.y) if observation.y is not None else None,
        )
    user.clock_offset_days = (simulated.days[-1].date - DAY).days + 3
    manager.advance()
    assert manager.evaluate(row.id)["label"] == "helped"


def test_first_null_cohort_patient_does_not_get_helped(db: Session) -> None:
    from sim.world import generate_world, simulate_experiment

    repo, user, manager = setup(db)
    world = generate_world(2000, patient_type="null")
    import_world(repo, user, world)
    row = manager.propose(exposure="magnesium", experiment_id=UUID(int=6021))
    manager.respond(row.id, "accept")
    simulated = simulate_experiment(world, PROTOCOL.validate_python(row.protocol), 1.0)
    for observation in simulated.observations:
        user.clock_offset_days = (observation.date - DAY).days
        manager.record_day(
            row.id,
            observation.date,
            observation.adherence,
            outcome_value=int(observation.y) if observation.y is not None else None,
        )
    user.clock_offset_days = (simulated.days[-1].date - DAY).days + 3
    manager.advance()
    assert manager.evaluate(row.id)["label"] != "helped"


def test_scan_requires_completed_checkin_span_and_new_data(db: Session) -> None:
    repo, user, manager = setup(db)
    surfacer = InsightSurfacer(repo, USER, clock=lambda: NOW)
    assert surfacer.scan_if_needed() is None
    repo.upsert_rating(USER, DAY, "fatigue", 3)
    repo.upsert_checkin(USER, DAY, completed=True)
    assert surfacer.scan_if_needed() is None
    for i in range(20):
        day = DAY - timedelta(days=i)
        repo.upsert_rating(USER, day, "fatigue", 3)
        repo.upsert_checkin(USER, day, completed=True, checklist_answered=True)
    assert surfacer.scan_if_needed() is not None
    assert surfacer.scan_if_needed() is None
    repo.upsert_rating(USER, DAY, "fatigue", 4)
    assert surfacer.scan_if_needed() is not None


def test_new_tools_are_code_only_and_completed_day_returns_409(db: Session) -> None:
    from app.agent.tools.registry import ToolRegistry

    repo, user, manager, row = accepted(db)
    tools = ToolRegistry(repo, USER, DAY, UUID(int=6040), clock=lambda: NOW)
    for name in (
        "propose_experiment",
        "respond_experiment",
        "record_experiment_day",
        "evaluate_experiment",
    ):
        assert tools.execute(name, {})["error"]["code"] == "tool_not_allowed"
    user.clock_offset_days = 17
    manager.advance()
    result = tools.execute(
        "record_experiment_day",
        {"id": str(row.id), "date": str(row.started_on), "adherence": True},
        allow_mutations=True,
    )
    assert result["error"]["status"] == 409


def test_protocol_calendar_is_not_a_current_instruction_exemption(db: Session) -> None:
    from app.agent.experiment_composer import compose_protocol
    from app.agent.safety.output_guard import Facts

    repo, user, manager = setup(db)
    row = manager.propose(exposure="coffee")
    result = compose_protocol(
        router_for("Please review the proposed plan."),
        row,
        manager,
        CallContext("composer_experiment", "synthetic", None, UUID(int=6041)),
    )
    assert not OutputGuard().check(result.text, result.facts)
    assert all(label in result.text for label in ("BASELINE", "ON", "OFF"))
    assert "G5" in OutputGuard().check("ON then OFF", Facts(kind="experiment", phase="on"))


def test_experiment_writes_are_user_scoped(db: Session) -> None:
    repo, user, manager, row = accepted(db)
    other = repo.create_user(UserInput(data_class="synthetic"))
    foreign = ExperimentManager(repo, other.id, clock=lambda: NOW)
    with pytest.raises(ExperimentError) as error:
        foreign.record_day(row.id, DAY, True)
    assert error.value.status_code == 404


def test_false_adherence_is_filled_but_not_usable(db: Session) -> None:
    repo, user, manager, row = accepted(db)
    plans = schedule(PROTOCOL.validate_python(row.protocol))
    user.clock_offset_days = 14
    for plan in plans:
        if plan.analysis:
            manager.record_day(row.id, plan.date, False, outcome_value=3)
    verdict = manager.evaluate(row.id)
    assert verdict["label"] == "inconclusive" and verdict["completeness"] == 0


def test_chat_proposal_acceptance_and_confirmed_abandon_flow(engine: Engine) -> None:
    import json

    from app.agent.orchestrator import Orchestrator
    from app.agent.progress import Progress, save_progress
    from app.agent.tracing import MemoryTraceStore, UserIdentity
    from app.domain.schemas import PendingState

    user_id = UUID(int=6050)
    with Session(engine) as session, session.begin():
        repo = Repository(session)
        repo.create_user(UserInput(data_class="synthetic"), user_id=user_id)
        repo.set_tracking(user_id, outcomes=[("fatigue", "lower")], exposures=["coffee"])
        save_progress(repo, user_id, Progress(date=DAY, onboarding="done"), PendingState())
        for i in range(5):
            mapped = map_event_time(DAY, "UTC", relative_day=-i)
            repo.add_event(
                user_id,
                EventInput(kind="meal", name="coffee"),
                ts=mapped.ts,
                local_date=mapped.local_date,
            )
    fake = FakeLLMClient(
        [
            LLMResponse(json.dumps(value), 10, 5)
            for value in [
                {
                    "intent": "experiment",
                    "experiment_action": "start",
                    "experiment_target": "coffee",
                },
                {"reply": "Please review the proposed plan."},
                {"reply": "Your plan is accepted."},
                {"intent": "experiment", "experiment_action": "abandon"},
                {"reply": "Please review your plan."},
            ]
        ]
    )
    router = LLMRouter(
        Settings(
            _env_file=None,
            llm_analyzer="ollama:fixture",
            llm_composer="ollama:fixture",
            llm_narrator="ollama:fixture",
        ),
        store=MemoryTraceStore(users=[UserIdentity(user_id, "synthetic", "UTC", False)]),
        prices=PriceBook({}),
        clients={"ollama": fake},
        clock=lambda: NOW,
    )
    chat = Orchestrator(engine, router, clock=lambda: NOW)
    try:
        proposed = chat.process(user_id, "test coffee")
        assert "Would you like to accept?" in proposed.reply
        accepted_reply = chat.process(user_id, "yes")
        assert accepted_reply.analyzer_calls == 0
        requested = chat.process(user_id, "abandon the experiment")
        assert "Would you like to abandon" in requested.reply
        with Session(engine) as session:
            row = session.scalar(select(m.Experiment).where(m.Experiment.user_id == user_id))
            assert row.status == "accepted"
        abandoned = chat.process(user_id, "yes")
        assert abandoned.reply == "The experiment is closed."
        with Session(engine) as session:
            row = session.scalar(select(m.Experiment).where(m.Experiment.user_id == user_id))
            assert row.status == "abandoned" and row.end_reason == "user"
    finally:
        with Session(engine) as session, session.begin():
            Repository(session).delete_user(user_id)

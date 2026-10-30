from collections.abc import Iterator
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Pattern
from app.db.repos import Repository
from app.db.session import create_db_engine
from app.domain.schemas import PatternRecord, UserInput

pytestmark = pytest.mark.p2


@pytest.fixture
def storage() -> Iterator[Session]:
    engine = create_db_engine(Settings().database_url_test)
    assert engine.url.database is not None and engine.url.database.endswith("_test")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                assert not inspect(connection).get_table_names()
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                with Session(connection, join_transaction_mode="create_savepoint") as session:
                    yield session
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def pattern(mode: str | None, n_valid: int | None) -> Pattern:
    return Pattern(
        user_id=UUID(int=801),
        run_id=UUID(int=802),
        pattern_key="walk|fog|0",
        exposure="walk",
        outcome="fog",
        lag_days=0,
        effect=-2,
        p_raw=0.01,
        p_adj=0.03,
        tier="weak",
        n_pairs=20,
        n_exposed=10,
        n_unexposed=10,
        perm_mode=mode,
        n_valid=n_valid,
        window_start=date(2026, 1, 1),
        window_end=date(2026, 1, 20),
        data_points=[],
    )


@pytest.mark.parametrize("mode,n_valid", [("exact", 120), ("mc", 500), (None, None)])
def test_pattern_permutation_metadata_round_trips(
    storage: Session, mode: str | None, n_valid: int | None
) -> None:
    Repository(storage).create_user(UserInput(), user_id=UUID(int=801))
    row = pattern(mode, n_valid)
    storage.add(row)
    storage.flush()
    storage.refresh(row)
    record = PatternRecord.model_validate(row)
    assert record.perm_mode == mode and record.n_valid == n_valid


@pytest.mark.parametrize("mode,n_valid", [("wrong", 120), ("exact", 0), (None, 120), ("mc", None)])
def test_pattern_permutation_metadata_constraints(
    storage: Session, mode: str | None, n_valid: int | None
) -> None:
    Repository(storage).create_user(UserInput(), user_id=UUID(int=801))
    with pytest.raises(IntegrityError), storage.begin_nested():
        storage.add(pattern(mode, n_valid))
        storage.flush()

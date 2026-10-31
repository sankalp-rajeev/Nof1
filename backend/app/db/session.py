"""Explicit engine/session factories. Never echo SQL parameters containing health data."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import DB_POOL_RECYCLE_SECONDS


def create_db_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError("Database URL must use postgresql+psycopg")
    if parsed.database and parsed.database.endswith("_test"):
        if parsed.host not in {"localhost", "127.0.0.1", "::1", None}:
            raise ValueError("Test databases must be local")
    # Numeric loopback avoids DNS in offline integration tests and is also
    # appropriate for the local Docker port mapping used in development.
    if parsed.host == "localhost":
        parsed = parsed.set(host="127.0.0.1")
    return create_engine(
        parsed,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_recycle=DB_POOL_RECYCLE_SECONDS,
        pool_size=3,
        max_overflow=2,
    )


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        yield session

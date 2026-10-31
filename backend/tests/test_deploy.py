"""Offline production boundary and idle-connection configuration checks."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import models as m
from app.db.session import create_db_engine
from app.main import create_app
from tests.test_storage import engine

pytestmark = pytest.mark.p7
__all__ = ["engine"]


def test_direct_connections_ping_and_recycle_before_neon_suspend() -> None:
    db = create_db_engine("postgresql+psycopg://nof1:nof1@localhost/nof1")
    try:
        assert db.pool._pre_ping is True
        assert 0 < db.pool._recycle < 300
        assert db.pool.size() == 3  # type: ignore[attr-defined]
        assert db.echo is False
        assert db.hide_parameters is True
    finally:
        db.dispose()


@pytest.mark.parametrize("debug", [False, True])
def test_production_cookie_debug_and_delete(engine: Engine, debug: bool) -> None:
    settings = Settings(_env_file=None, app_env="prod", debug=debug)
    with TestClient(
        create_app(settings=settings, engine=engine), base_url="https://nof1.test"
    ) as client:
        response = client.get("/api/tracking")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert all(flag in cookie for flag in ("secure", "httponly", "samesite=lax", "path=/"))
        assert "domain=" not in cookie
        uid = UUID(client.cookies["nof1_uid"])
        assert client.get("/api/debug/llm_calls").status_code == 404
        assert client.delete("/api/me").json() == {"deleted": True}
        assert "nof1_uid" not in client.cookies
        with Session(engine) as session:
            assert session.get(m.User, uid) is None

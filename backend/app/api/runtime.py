"""Lazy runtime configuration and bounded in-memory request limits."""

from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

from sqlalchemy import Engine
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.agent.llm.cost import PriceBook
from app.agent.llm.router import LLMRouter
from app.agent.tracing import SQLTraceStore
from app.config import Settings
from app.db.session import create_db_engine


class Runtime:
    def __init__(
        self,
        settings: Settings | None,
        engine: Engine | None,
        router: LLMRouter | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._settings, self._engine, self._router = settings, engine, router
        self.clock = clock
        self.requests: dict[UUID, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = Settings()
        return self._settings

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_db_engine(self.settings.database_url)
        return self._engine

    @property
    def router(self) -> LLMRouter:
        if self._router is None:
            self._router = LLMRouter(
                self.settings,
                store=SQLTraceStore(self.engine),
                prices=PriceBook.load(),
                mode="app",
                clock=self.clock,
            )
        return self._router

    def allowed(self, user_id: UUID) -> bool:
        instant = self.clock().timestamp()
        with self.lock:
            requests = self.requests[user_id]
            while requests and requests[0] <= instant - 60:
                requests.popleft()
            if len(requests) >= 30:
                return False
            requests.append(instant)
        return True


class ConfiguredCORS:
    def __init__(self, app: ASGIApp, runtime: Runtime) -> None:
        self.app, self.runtime = app, runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        cors = CORSMiddleware(
            self.app,
            allow_origins=[self.runtime.settings.frontend_origin],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
        )
        await cors(scope, receive, send)


def utc_now() -> datetime:
    return datetime.now(UTC)

"""Scoped API entry point. Health performs no database, configuration or LLM I/O."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import JsonValue
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.agent.experiment_manager import ExperimentError, ExperimentManager
from app.agent.llm.router import LLMRouter
from app.agent.orchestrator import Orchestrator
from app.agent.pending import question_text
from app.agent.safety.templates import ESCALATION
from app.api.demo import advance_demo, load_demo
from app.api.runtime import ConfiguredCORS, Runtime, utc_now
from app.api.schemas import AdvanceInput, ChatInput, DayInput, ProposalInput
from app.api.views import experiment_view, insights_view, row_json, tracking_view
from app.config import Settings
from app.db import models as m
from app.db.repos import Repository
from app.domain.clock import today
from app.domain.schemas import UserInput


def failure(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app(
    *,
    settings: Settings | None = None,
    engine: Engine | None = None,
    router: LLMRouter | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    runtime = Runtime(settings, engine, router, clock)
    app = FastAPI(title="Nof1", version="0.1.0")
    app.state.runtime = runtime

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return failure("validation", "Check the request fields.", 422)

    @app.exception_handler(ExperimentError)
    async def experiment_error(request: Request, error: ExperimentError) -> JSONResponse:
        return failure(error.code, str(error), error.status_code)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return failure(
            "not_found" if error.status_code == 404 else "request_error",
            "The requested resource is unavailable.",
            error.status_code,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        return failure("database_unavailable", "The service is temporarily unavailable.", 503)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        return failure("internal_error", "The request could not be completed.", 500)

    @app.middleware("http")
    async def identity(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/api/") or request.method == "OPTIONS":
            return await call_next(request)
        raw = request.cookies.get("nof1_uid")
        try:
            user_id = UUID(raw) if raw else None
        except ValueError:
            user_id = None
        fresh = False
        try:
            with Session(runtime.engine) as session, session.begin():
                repo = Repository(session)
                if user_id is None or repo.get_user(user_id) is None:
                    user_id = repo.create_user(UserInput()).id
                    fresh = True
            request.state.user_id = user_id
            response = (
                await call_next(request)
                if runtime.allowed(user_id)
                else failure("rate_limit", "Please wait before trying again.", 429)
            )
            if fresh and request.method != "DELETE":
                response.set_cookie(
                    "nof1_uid",
                    str(user_id),
                    httponly=True,
                    secure=runtime.settings.app_env == "prod",
                    samesite="lax",
                    max_age=31536000,
                    path="/",
                )
            return response
        except SQLAlchemyError:
            return failure("database_unavailable", "The service is temporarily unavailable.", 503)

    app.add_middleware(ConfiguredCORS, runtime=runtime)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/tracking")
    def tracking(request: Request) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session:
            return tracking_view(Repository(session), request.state.user_id, runtime)

    @app.get("/api/messages")
    def messages(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[JsonValue]:
        with Session(runtime.engine) as session:
            output: list[JsonValue] = []
            for row in Repository(session).list_messages(request.state.user_id, limit=limit):
                payload = row_json(row)
                payload.pop("response_payload", None)
                payload["red_flag"] = row.role == "assistant" and row.content == ESCALATION
                output.append(payload)
            return output

    @app.post("/api/chat")
    def chat(request: Request, body: ChatInput) -> dict[str, JsonValue]:
        uid = request.state.user_id
        with Session(runtime.engine) as session, session.begin():
            Orchestrator._lock(session, uid)
            repo = Repository(session)
            previous = repo.find_message(uid, body.client_msg_id) if body.client_msg_id else None
            if previous is not None:
                stored = session.scalar(
                    select(m.Message).where(
                        m.Message.user_id == uid,
                        m.Message.trace_id == previous.trace_id,
                        m.Message.role == "assistant",
                    )
                )
                if stored is not None and stored.response_payload is not None:
                    return stored.response_payload
            user = repo._user(uid, lock=True)
            previous_day = today(user, now=runtime.clock())
            user.tz = body.tz
            if user.is_demo:
                user.clock_offset_days += (previous_day - today(user, now=runtime.clock())).days
        result = Orchestrator(runtime.engine, runtime.router, clock=runtime.clock).process(
            uid, body.message, client_msg_id=body.client_msg_id
        )
        with Session(runtime.engine) as session, session.begin():
            repo = Repository(session)
            Orchestrator._lock(session, uid)
            reply = session.scalar(
                select(m.Message).where(
                    m.Message.user_id == uid,
                    m.Message.trace_id == result.trace_id,
                    m.Message.role == "assistant",
                )
            )
            assert reply is not None
            if reply.response_payload is not None:
                return reply.response_payload
            user_message = session.scalar(
                select(m.Message.id).where(
                    m.Message.user_id == uid,
                    m.Message.trace_id == result.trace_id,
                    m.Message.role == "user",
                )
            )
            events: list[JsonValue] = [
                row_json(row)
                for row in session.scalars(
                    select(m.Event).where(
                        m.Event.user_id == uid, m.Event.message_id == user_message
                    )
                )
            ]
            pending = repo.get_state(uid).pending
            payload: dict[str, JsonValue] = {
                "reply": result.reply,
                "events_logged": events,
                "pending_question": question_text(pending) if pending else None,
                "safety": {"red_flag": result.reply == ESCALATION},
                "new_insight": result.facts.details
                if result.facts and result.facts.kind == "insight"
                else None,
                "experiment_prompt": result.facts.details
                if result.facts and result.facts.kind in {"experiment", "protocol", "verdict"}
                else None,
                "limited_mode": result.limited,
                "trace_id": str(result.trace_id),
            }
            reply.response_payload = payload
            return payload

    @app.get("/api/timeline")
    def timeline(
        request: Request, days: int = Query(default=30, ge=1, le=365)
    ) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session:
            repo = Repository(session)
            uid = request.state.user_id
            day = today(repo._user(uid), now=runtime.clock())
            start = day - timedelta(days=days - 1)
            events = repo.latest_events(uid, start, day)
            ratings = repo.list_ratings(uid, start, day)
            checkins = {
                row.local_date: row
                for row in session.scalars(
                    select(m.Checkin).where(
                        m.Checkin.user_id == uid,
                        m.Checkin.local_date >= start,
                        m.Checkin.local_date <= day,
                    )
                )
            }
            output: list[JsonValue] = []
            for index in range(days):
                current = start + timedelta(days=index)
                checkin = checkins.get(current)
                output.append(
                    {
                        "date": current.isoformat(),
                        "events": [row_json(row) for row in events if row.local_date == current],
                        "ratings": [row_json(row) for row in ratings if row.local_date == current],
                        "checklist_answered": bool(checkin and checkin.checklist_answered),
                        "completed": bool(checkin and checkin.completed),
                    }
                )
            return {"today": day.isoformat(), "days": output}

    @app.get("/api/insights")
    def insights(request: Request) -> list[JsonValue]:
        with Session(runtime.engine) as session:
            return insights_view(Repository(session), request.state.user_id, runtime)

    @app.get("/api/experiments/current")
    def current(request: Request) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session, session.begin():
            Orchestrator._lock(session, request.state.user_id)
            return experiment_view(Repository(session), request.state.user_id, runtime)

    @app.post("/api/experiments")
    def propose(request: Request, body: ProposalInput) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session, session.begin():
            uid = request.state.user_id
            Orchestrator._lock(session, uid)
            repo = Repository(session)
            row = ExperimentManager(repo, uid, clock=runtime.clock).propose(
                pattern_id=body.pattern_id, exposure=body.exposure, outcome=body.outcome
            )
            return experiment_view(repo, uid, runtime, row)

    @app.post("/api/experiments/{id}/accept")
    def accept(request: Request, id: UUID) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session, session.begin():
            uid = request.state.user_id
            Orchestrator._lock(session, uid)
            repo = Repository(session)
            row = ExperimentManager(repo, uid, clock=runtime.clock).respond(
                id, "accept", confirmed=True
            )
            return experiment_view(repo, uid, runtime, row)

    @app.post("/api/experiments/{id}/abandon")
    def abandon(request: Request, id: UUID) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session, session.begin():
            uid = request.state.user_id
            Orchestrator._lock(session, uid)
            repo = Repository(session)
            manager = ExperimentManager(repo, uid, clock=runtime.clock)
            manager.request_abandon(id)
            row = manager.respond(id, "abandon", confirmed=True)
            return experiment_view(repo, uid, runtime, row)

    @app.put("/api/experiments/{id}/days/{day}")
    def record_day(request: Request, id: UUID, day: date, body: DayInput) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session, session.begin():
            uid = request.state.user_id
            Orchestrator._lock(session, uid)
            repo = Repository(session)
            manager = ExperimentManager(repo, uid, clock=runtime.clock)
            manager.advance()
            row = manager._owned(id)
            if row.status in {"completed", "abandoned"}:
                raise ExperimentError(
                    "terminal", "The experiment has ended; its snapshot cannot be changed.", 409
                )
            plan = session.scalar(
                select(m.ExperimentDay).where(
                    m.ExperimentDay.experiment_id == id, m.ExperimentDay.date == day
                )
            )
            if day > manager.day() or plan is None:
                raise ExperimentError(
                    "invalid_date", "Choose a scheduled date on or before today.", 422
                )
            return row_json(
                manager.record_day(id, day, body.adherence, outcome_value=body.outcome_value)
            )

    @app.post("/api/demo/load")
    def demo_load(request: Request) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session, session.begin():
            uid = request.state.user_id
            Orchestrator._lock(session, uid)
            repo = Repository(session)
            load_demo(repo, uid, runtime.clock)
            return tracking_view(repo, uid, runtime)

    @app.post("/api/demo/advance")
    def demo_advance(request: Request, body: AdvanceInput) -> dict[str, JsonValue]:
        with Session(runtime.engine) as session, session.begin():
            uid = request.state.user_id
            Orchestrator._lock(session, uid)
            repo = Repository(session)
            advance_demo(repo, uid, body.days, runtime.clock)
            return experiment_view(repo, uid, runtime)

    @app.delete("/api/me")
    def delete_me(request: Request) -> JSONResponse:
        with Session(runtime.engine) as session, session.begin():
            Orchestrator._lock(session, request.state.user_id)
            Repository(session).delete_user(request.state.user_id)
        response = JSONResponse({"deleted": True})
        response.delete_cookie(
            "nof1_uid",
            path="/",
            httponly=True,
            samesite="lax",
            secure=runtime.settings.app_env == "prod",
        )
        return response

    @app.get("/api/debug/llm_calls")
    def debug_calls(request: Request) -> list[JsonValue]:
        if not runtime.settings.debug:
            raise HTTPException(404)
        with Session(runtime.engine) as session:
            return [
                row_json(row)
                for row in session.scalars(
                    select(m.LLMCall)
                    .where(m.LLMCall.user_id == request.state.user_id)
                    .order_by(m.LLMCall.created_at)
                )
            ]

    return app


app = create_app()

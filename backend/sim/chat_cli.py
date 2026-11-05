"""Manual, spend-capped synthetic chat evaluation and network-free replay."""

import argparse
import json
import os
import re
from decimal import Decimal
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from app.agent.llm.base import ProviderError
from app.agent.llm.cost import PriceBook
from app.agent.tracing import SQLTraceStore
from app.config import ROOT, Settings
from app.db.session import create_db_engine
from sim.chat_runner import run_chat
from sim.cli import revision, source_digest
from sim.config import (
    CHAT_DAYS,
    COHORT_L,
    E4_OLLAMA_BASE_URL,
    E4_PERSONA_KEEP_ALIVE,
    E4_PERSONA_RETRY_WAITS_S,
    E4_PERSONA_TIMEOUT_S,
    E4_RUN2_MAX_SPEND_USD,
    LIVE_MAX_CALLS,
)
from sim.gpu_preflight import require_free_vram
from sim.live_limits import LimitedRouter, LiveLimits, claim_run
from sim.ollama_recovery import PersonaRecovery, ollama_ready
from sim.replay import ReplayBundle, replay_bundle, score_dict


def require_budget(value: float | None) -> float:
    if value is None or not 0 < value < float("inf"):
        raise ValueError(
            "Set an explicit positive MAX_SPEND_USD or --budget before live/final evaluation"
        )
    return value


def family(route: str) -> str:
    provider, model = route.split(":", 1)
    if provider != "ollama":
        return provider
    return re.split(r"[\d:.-]", model.rsplit("/", 1)[-1])[0]


def authorization_claim(*, e4_only: bool) -> Path:
    scope = "e4" if e4_only else "live"
    return ROOT / f"evals/reports/p8-authorized-{scope}-2026-11-04"


def live_settings(budget: float, persona: str | None, extractor: str | None) -> Settings:
    updates: dict[str, object] = {"max_spend_usd": require_budget(budget)}
    if persona:
        updates["sim_persona"] = persona
    if extractor:
        updates["llm_analyzer"] = extractor
    settings = Settings.model_validate({**Settings().model_dump(), **updates})
    for purpose, route in (
        ("persona", settings.sim_persona),
        ("analyzer", settings.llm_analyzer),
        ("composer", settings.llm_composer),
        ("narrator", settings.llm_narrator),
    ):
        if "CHANGE_ME" in route:
            raise ValueError(f"Configure verified model for purpose={purpose}, id={route}")
    if family(settings.sim_persona) == family(settings.llm_analyzer):
        raise ValueError("Persona and extractor must use different model families")
    return settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("fixture", type=Path)
    live = sub.add_parser("live")
    live.add_argument("--budget", type=float, default=os.environ.get("MAX_SPEND_USD"))
    live.add_argument("--persona")
    live.add_argument("--extractor")
    live.add_argument("--max-calls", type=int, default=LIVE_MAX_CALLS)
    live.add_argument("--e4-only", action="store_true", help="Separate authorized cohort-only run")
    live.add_argument("--e4-run2", action="store_true", help="Fresh separately authorized E4 run 2")
    live.add_argument("--e4-run3", action="store_true", help="Fresh separately authorized E4 run 3")
    live.add_argument("--e4-run4", action="store_true", help="Fresh separately authorized E4 run 4")
    live.add_argument("--patients", type=int, default=len(COHORT_L), choices=range(1, 31))
    live.add_argument("--days", type=int, default=CHAT_DAYS, choices=range(1, CHAT_DAYS + 1))
    live.add_argument("--output", type=Path, default=ROOT / "evals/reports/p8-live")
    args = parser.parse_args(argv)
    if args.command == "replay":
        bundle = ReplayBundle.model_validate_json(args.fixture.read_bytes())
        result = replay_bundle(bundle)
        print(
            json.dumps(
                {
                    "mode": "offline_replay",
                    "provenance": bundle.provenance,
                    "extraction": score_dict(result),
                }
            )
        )
        return 0
    budget = require_budget(args.budget)
    if sum((args.e4_run2, args.e4_run3, args.e4_run4)) > 1:
        raise ValueError("Choose exactly one E4 run authorization")
    separate_e4_run = args.e4_run2 or args.e4_run3 or args.e4_run4
    if separate_e4_run and (
        not args.e4_only or args.patients != len(COHORT_L) or args.days != CHAT_DAYS
    ):
        raise ValueError(
            "Separate E4 runs require E4-only scope and the full 30-patient, 30-day cohort"
        )
    ceiling = Decimal(E4_RUN2_MAX_SPEND_USD) if separate_e4_run else Decimal("1.00")
    if Decimal(str(budget)) > ceiling or not 0 < args.max_calls <= LIVE_MAX_CALLS:
        raise ValueError(f"Authorized live ceilings: ${ceiling} and 5000 dispatch attempts")
    if os.environ.get("DATA_CLASS") != "synthetic":
        raise ValueError("Live evaluation requires DATA_CLASS=synthetic")
    settings = live_settings(budget, args.persona, args.extractor)
    if args.e4_only:
        settings = settings.model_copy(update={"ollama_base_url": E4_OLLAMA_BASE_URL})
    if args.output.exists():
        raise FileExistsError(
            "Choose a new output directory; prior eval evidence is not overwritten"
        )
    free_vram_mib = None
    if args.e4_run4:
        try:
            free_vram_mib = require_free_vram()
        except ProviderError as error:
            print(json.dumps({"stopped": "gpu_preflight_failed", "reason": error.code}), flush=True)
            return 1  # No generation or authorization claim before the VRAM check passes.
    engine = create_db_engine(settings.database_url)
    try:
        # A fixed claim prevents accidentally consuming this authorization twice,
        # even with a different output argument or after an interrupted process.
        authorization = authorization_claim(e4_only=args.e4_only)
        if args.e4_run4:
            authorization = authorization.with_name(authorization.name + "-run-4")
        elif args.e4_run3:
            authorization = authorization.with_name(authorization.name + "-run-3")
        elif args.e4_run2:
            authorization = authorization.with_name(authorization.name + "-run-2")
        claim_run(authorization)
        claim_run(args.output)
        limits = LiveLimits(
            PriceBook.load(),
            args.output / "ledger.json",
            max_calls=args.max_calls,
            cap=Decimal(str(budget)),
            e4_run2=separate_e4_run,
        )
        router = LimitedRouter(settings, store=SQLTraceStore(engine), prices=limits.prices)
        router.tape = []
        router.limits = limits
        if args.e4_only:
            router.persona_timeout_s = E4_PERSONA_TIMEOUT_S
            router.persona_recovery = PersonaRecovery(
                lambda: ollama_ready(settings.ollama_base_url)
            )
        metadata = {
            "revision": revision(),
            "source_digest": source_digest(),
            "persona": settings.sim_persona,
            "analyzer": settings.llm_analyzer,
            "composer": settings.llm_composer,
            "narrator": settings.llm_narrator,
            "max_output_tokens": settings.max_output_tokens,
            "llm_timeout_s": settings.llm_timeout_s,
            "persona_timeout_s": router.persona_timeout_s or settings.llm_timeout_s,
            "persona_keep_alive": E4_PERSONA_KEEP_ALIVE if args.e4_only else None,
            "persona_transport": "ollama_native_chat" if args.e4_only else "configured",
            "persona_retry_waits_s": E4_PERSONA_RETRY_WAITS_S if args.e4_only else (),
            "persona_warmup_enabled": args.e4_only,
            "ollama_base_url": settings.ollama_base_url,
            "evaluation_scope": "E4_only" if args.e4_only else "safety_then_cohort",
            "safety_cases_enabled": not args.e4_only,
            "e4_run": 4 if args.e4_run4 else 3 if args.e4_run3 else 2 if args.e4_run2 else None,
            "persona_gpu_preflight_enabled": args.e4_run4,
            "free_vram_mib_before_warmup": free_vram_mib,
            "patients": args.patients,
            "days": args.days,
            "pricebook": (ROOT / "config/prices.yaml").read_text(encoding="utf-8"),
        }
        (args.output / "configuration.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "hard_max_calls": args.max_calls,
                    "hard_spend_cap_usd": budget,
                    "estimated_cost_upper_bound_usd": budget,
                    "cost_estimate_method": "conservative admission bound; not a token forecast",
                    "ordering": "E4 cohort only; no safety cases"
                    if args.e4_only
                    else "25 safety cases before cohort",
                }
            ),
            flush=True,
        )
        try:
            report, _ = run_chat(
                settings,
                engine,
                seeds=range(args.patients),
                days=args.days,
                router=router,
                limits=limits,
                include_e7=not args.e4_only,
                warmup_persona_enabled=args.e4_only,
            )
        except BaseException as error:
            # Preserve failures without allowing exceptions/tracebacks to leak payloads.
            report = {
                "stopped": "driver_error",
                "exception_class": type(error).__name__,
                "failure_case_ids": {"driver_error": [limits.case_id]},
            }
        report["limits"] = TypeAdapter(JsonValue).validate_python(limits.summary())
        report["evaluation_scope"] = "E4_only" if args.e4_only else "safety_then_cohort"
        report["safety_cases_enabled"] = not args.e4_only
        if router.persona_recovery is not None:
            recovery = router.persona_recovery
            report["persona_recovery"] = {
                "readiness_checks": recovery.readiness_checks,
                "retry_dispatches": recovery.retry_dispatches,
                "exhausted": recovery.exhausted,
                "last_provider_error": recovery.last_error,
            }
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        e7 = report.get("E7", {"failed": []})
        assert isinstance(e7, dict)
        return int(report["stopped"] is not None or bool(e7["failed"]))
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

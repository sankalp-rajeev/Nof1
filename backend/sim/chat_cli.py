"""Manual, spend-capped synthetic chat evaluation and network-free replay."""

import argparse
import json
import os
import re
from pathlib import Path

from app.config import ROOT, Settings
from app.db.session import create_db_engine
from sim.chat_runner import run_chat
from sim.config import CHAT_DAYS, COHORT_L
from sim.replay import ReplayBundle, replay_bundle, score_dict, write_bundle


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
    settings = live_settings(budget, args.persona, args.extractor)
    if args.output.exists():
        raise FileExistsError(
            "Choose a new output directory; prior eval evidence is not overwritten"
        )
    engine = create_db_engine(settings.database_url)
    try:
        report, bundle = run_chat(settings, engine, seeds=range(args.patients), days=args.days)
        args.output.mkdir(parents=True)
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        write_bundle(bundle, args.output / "replay.json")
        print(json.dumps(report, indent=2))
        e7 = report["E7"]
        assert isinstance(e7, dict)
        return int(report["stopped"] is not None or bool(e7["failed"]))
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

"""Human-triggered, exclusive final protocol. Never called by a gate or CI."""

import argparse
import json
import os

from app.config import ROOT
from app.db.session import create_db_engine
from app.stats.config import N_PERM
from sim.chat_cli import live_settings, require_budget
from sim.chat_runner import run_chat
from sim.cli import phase_approved, revision, source_digest
from sim.config import FINAL_A, FINAL_L, FINAL_N, FINAL_V
from sim.final_scope import FINAL_SEEDS_ALLOWED
from sim.replay import write_bundle
from sim.report import write_reports
from sim.runner import evaluate_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=os.environ.get("MAX_SPEND_USD"))
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Also run held-out synthetic chat; requires separate persona configuration",
    )
    parser.add_argument("--persona")
    parser.add_argument("--extractor")
    args = parser.parse_args(argv)
    budget = require_budget(args.budget)
    if not phase_approved(8):
        raise ValueError("Human approval of P8 is required before final evaluation")
    from subprocess import run

    status = run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError("Freeze and commit the code before final evaluation")
    settings = live_settings(budget, args.persona, args.extractor) if args.chat else None
    output = ROOT / "evals/reports/final"
    # Exclusive durable sentinel; even a failed/partial run needs explicit human
    # authorization before recovery. Never silently rerun or tune held-out seeds.
    output.mkdir(parents=True, exist_ok=True)
    with (output / "STARTED.json").open("x", encoding="utf-8") as handle:
        json.dump({"revision": revision(), "budget": budget, "chat_requested": args.chat}, handle)
    token = FINAL_SEEDS_ALLOWED.set(True)
    chat_failed = False
    try:
        report = evaluate_suite(
            n_perm=N_PERM,
            scan_seeds=FINAL_A,
            null_seeds=FINAL_N,
            verdict_seeds=FINAL_V,
        )
        write_reports([report], output, revision=revision(), source_digest=source_digest())
        if settings is not None:
            engine = create_db_engine(settings.database_url)
            try:
                chat_report, bundle = run_chat(settings, engine, seeds=FINAL_L)
                (output / "chat.json").write_text(
                    json.dumps(chat_report, indent=2) + "\n", encoding="utf-8"
                )
                write_bundle(bundle, output / "chat-replay.json")
                e7 = chat_report["E7"]
                assert isinstance(e7, dict)
                chat_failed = chat_report["stopped"] is not None or bool(e7["failed"])
            finally:
                engine.dispose()
        return int(bool(report.failures()) or chat_failed)
    finally:
        FINAL_SEEDS_ALLOWED.reset(token)


if __name__ == "__main__":
    raise SystemExit(main())

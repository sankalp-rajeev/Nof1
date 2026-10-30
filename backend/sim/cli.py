"""Offline P3 commands. No provider SDKs or held-out evaluation entry points."""

import argparse
import hashlib
import subprocess
from pathlib import Path

from app.stats.config import N_PERM, N_PERM_FAST
from sim.config import REGRESSION_A, REGRESSION_N
from sim.demo import find_demo_seed
from sim.report import read_baseline, stats_components, write_initial_baseline, write_reports
from sim.runner import evaluate_suite
from sim.scoring import compare_regression

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "evals" / "baselines" / "stats_baseline.json"


def revision() -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def source_digest() -> str:
    digest = hashlib.sha256()
    paths = [
        *sorted((ROOT / "backend" / "sim").glob("*.py")),
        *sorted((ROOT / "backend" / "app" / "stats").glob("*.py")),
        ROOT / "backend" / "pyproject.toml",
        ROOT / "backend" / "uv.lock",
    ]
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def regression_components() -> dict[str, dict[str, float]]:
    report = evaluate_suite(
        n_perm=N_PERM_FAST,
        include_power=False,
        include_verdicts=False,
        scan_seeds=REGRESSION_A,
        null_seeds=REGRESSION_N,
    )
    return stats_components(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["stats", "regression", "init-baseline", "find-demo"])
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "reports")
    args = parser.parse_args()
    if args.command == "find-demo":
        print(find_demo_seed(), flush=True)
        return 0
    if args.command == "init-baseline":
        if BASELINE.exists():
            raise FileExistsError(
                "Initial baseline already exists; "
                "explicit human authorization is required to change it"
            )
        write_initial_baseline(BASELINE, regression_components(), revision=revision())
        print(f"Created {BASELINE}; pending human approval", flush=True)
        return 0
    if args.command == "regression":
        issues = compare_regression(regression_components(), read_baseline(BASELINE))
        print(
            "\n".join(issues)
            if issues
            else "P3 stats regression PASS (baseline approval tracked in STATUS.md)",
            flush=True,
        )
        return int(bool(issues))
    reports = []
    for budget in (N_PERM_FAST, N_PERM):
        report = evaluate_suite(n_perm=budget, progress=lambda message: print(message, flush=True))
        reports.append(report)
        print(
            f"n_perm={budget}: E1={report.e1.value}, E2={report.e2.value}, E3={report.e3.value}",
            flush=True,
        )
    write_reports(reports, args.output, revision=revision(), source_digest=source_digest())
    failures = [
        f"n_perm={report.n_perm}: {issue}" for report in reports for issue in report.failures()
    ]
    if failures:
        print("\n".join(failures), flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())

"""Run offline lint and tests cumulatively through one approved phase boundary."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.tasks import lint, tests


def marker_expression(phase: int) -> str:
    if not 0 <= phase <= 9:
        raise ValueError("Phase must be between 0 and 9")
    return f"({' or '.join(f'p{index}' for index in range(phase + 1))}) and not live"


def frontend_expression(phase: int) -> str:
    marker_expression(phase)
    return rf"\[p[0-{phase}]\]"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, type=int, choices=range(10))
    phase = parser.parse_args().phase
    marker = marker_expression(phase)
    print(f"P{phase} cumulative gate: {marker}", flush=True)
    lint()
    tests(marker, frontend_expression(phase))
    print(f"P{phase} gate PASS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

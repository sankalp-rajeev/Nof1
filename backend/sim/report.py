"""Serializable evaluation reports and exclusive, one-time baseline creation."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from sim.config import E1_MAX, E2_MIN, E3_MAX


@dataclass(frozen=True)
class Rate:
    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        return self.numerator / self.denominator if self.denominator else None

    def to_dict(self) -> dict[str, int | float | None]:
        return {"numerator": self.numerator, "denominator": self.denominator, "value": self.value}


@dataclass(frozen=True)
class Cohort:
    n: int
    first_seed: int | None
    last_seed: int | None
    days: int


@dataclass(frozen=True)
class VerdictCell:
    counts: dict[str, int]
    reference: str
    correct: int
    n: int


@dataclass(frozen=True)
class EvaluationReport:
    n_perm: int
    cohorts: dict[str, Cohort]
    e1: Rate
    e2: Rate
    e3: Rate
    e1c: dict[str, Rate]
    e1s: dict[str, Rate]
    e2b: dict[str, dict[str, Rate]]
    e3b: dict[str, VerdictCell]
    completeness: tuple[float, ...]
    configuration: dict[str, JsonValue] = field(default_factory=dict)

    def failures(self) -> list[str]:
        issues: list[str] = []
        for name, rate, limit, lower in [
            ("E1", self.e1, E1_MAX, False),
            ("E2", self.e2, E2_MIN, True),
            ("E3", self.e3, E3_MAX, False),
        ]:
            if rate.value is None or (rate.value < limit if lower else rate.value > limit):
                issues.append(f"{name}: {rate.value}, requires {'>=' if lower else '<='} {limit}")
        return issues

    def to_dict(self) -> dict[str, JsonValue]:
        payload = {
            "schema_version": 1,
            "n_perm": self.n_perm,
            "cohorts": {name: asdict(cohort) for name, cohort in self.cohorts.items()},
            "metrics": {
                "E1": self.e1.to_dict(),
                "E2": self.e2.to_dict(),
                "E3": self.e3.to_dict(),
                "E1c": {name: rate.to_dict() for name, rate in self.e1c.items()},
                "E1s": {name: rate.to_dict() for name, rate in self.e1s.items()},
                "E2b": {
                    t: {beta: rate.to_dict() for beta, rate in values.items()}
                    for t, values in self.e2b.items()
                },
                "E3b": {name: asdict(cell) for name, cell in self.e3b.items()},
            },
            "completeness": list(self.completeness),
            "configuration": self.configuration,
            "hard_gate_failures": self.failures(),
        }
        return TypeAdapter(dict[str, JsonValue]).validate_python(payload)


def stats_components(report: EvaluationReport) -> dict[str, dict[str, float]]:
    result: dict[str, float] = {}
    for name, rate in [("E1", report.e1), ("E2", report.e2), ("E3", report.e3)]:
        if rate.value is None:
            raise ValueError(f"Cannot baseline an absent metric: {name}")
        result[name] = rate.value
    return {"stats": result}


def write_initial_baseline(
    path: Path, components: dict[str, dict[str, float]], *, revision: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "approval": "pending human approval",
        "revision": revision,
        "components": components,
        "scope": {"n_perm": 500, "A": [0, 59], "N": [2000, 2099]},
    }
    # Exclusive mode prevents accidental regeneration, including after an interrupted CLI run.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def read_baseline(path: Path) -> dict[str, dict[str, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return TypeAdapter(dict[str, dict[str, float]]).validate_python(payload["components"])


def _rate_line(name: str, rate: Rate) -> str:
    value = f"{rate.value:.4f}" if rate.value is not None else "not evaluated"
    return f"- {name}: {value} ({rate.numerator}/{rate.denominator})"


def write_reports(
    reports: list[EvaluationReport], directory: Path, *, revision: str, source_digest: str
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "revision": revision,
        "source_digest": source_digest,
        "baseline_approval": "pending human approval",
        "reports": {str(report.n_perm): report.to_dict() for report in reports},
    }
    (directory / "p3-stats.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# P3 stats-only evaluation",
        "",
        f"Source revision: {revision}",
        f"Source digest: {source_digest}",
        "",
        "Initial regression baseline: pending human approval.",
        "No held-out seeds, live LLMs, or real user data were used.",
        "",
    ]
    for report in reports:
        lines.extend(
            [
                f"## Permutation budget {report.n_perm}",
                "",
                _rate_line("E1 null false-positive share", report.e1),
                _rate_line("E2 recall at |beta| = 3", report.e2),
                _rate_line("E3 null decisive verdict share", report.e3),
                "- Hard gates: "
                + ("PASS" if not report.failures() else "; ".join(report.failures())),
                "",
                "### Confounding (E1c)",
                "",
            ]
        )
        lines.extend(_rate_line(name, rate) for name, rate in report.e1c.items())
        lines.extend(
            [
                "",
                "Flagged and unflagged patient shares can overlap "
                "when different lags behave differently.",
                "A much larger unflagged share indicates the confounder heuristic rarely fires.",
                "",
                "### Short sleep by gamma tercile (E1s)",
                "",
            ]
        )
        lines.extend(_rate_line(name, rate) for name, rate in report.e1s.items())
        lines.extend(["", "### Power curve (E2b)", ""])
        for duration, values in report.e2b.items():
            lines.extend(
                _rate_line(f"T={duration}, |beta|={beta}", rate) for beta, rate in values.items()
            )
        lines.extend(["", "### Verdict matrix (E3b)", ""])
        lines.extend(
            f"- {name}: {cell.counts}; reference={cell.reference}; correct={cell.correct}/{cell.n}"
            for name, cell in report.e3b.items()
        )
        if report.completeness:
            completeness_values = sorted(report.completeness)
            lines.extend(
                [
                    f"- Completeness: min={completeness_values[0]:.3f}, "
                    f"median={completeness_values[len(completeness_values) // 2]:.3f}, "
                    f"max={completeness_values[-1]:.3f}; full distribution in JSON."
                ]
            )
        lines.append("")
    lines.extend(
        [
            "## Limits",
            "",
            "Four versus four analysis days have low power. The bootstrap ignores autocorrelation;",
            "One-day washout assumes limited carryover. "
            "This is an unblinded, single-person method.",
            "The report includes all measured outcomes, even when a hard gate fails.",
            "",
        ]
    )
    (directory / "p3-stats.md").write_text("\n".join(lines), encoding="utf-8")

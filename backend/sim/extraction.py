"""Pure PRD 10.1 event matching. Inputs contain observations, never planted effects."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from app.domain.normalize import normalize
from app.domain.schemas import DomainModel, Kind, Rating


class Label(DomainModel):
    kind: Kind
    name: str = Field(min_length=1)
    relative_day: int = Field(default=0, ge=-6, le=0)
    status: Literal["done", "skipped"] = "done"
    value: float | None = Field(default=None, allow_inf_nan=False)
    severity: Rating | None = None
    unit: str | None = None


@dataclass(frozen=True)
class ExtractionScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def f1(self) -> float:
        denominator = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / denominator if denominator else 1.0

    def __add__(self, other: "ExtractionScore") -> "ExtractionScore":
        return ExtractionScore(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)


def identity(event: Label) -> tuple[str, str, int]:
    return event.kind, normalize(event.name).canonical, event.relative_day


def score_extraction(gold: Sequence[Label], predicted: Sequence[Label]) -> ExtractionScore:
    remaining = list(gold)
    tp = fp = fn = 0
    for prediction in predicted:
        index = next(
            (i for i, row in enumerate(remaining) if identity(row) == identity(prediction)), None
        )
        if index is None:
            fp += 1
            continue
        expected = remaining.pop(index)
        matches = prediction.status == expected.status
        if expected.value is not None:
            matches &= prediction.value is not None and abs(
                prediction.value - expected.value
            ) <= max(abs(expected.value) * 0.1, 0.5)
        if expected.severity is not None:
            matches &= (
                prediction.severity is not None
                and abs(prediction.severity - expected.severity) <= 1
            )
        if matches:
            tp += 1
        else:
            fp += 1
            fn += 1
    return ExtractionScore(tp, fp, fn + len(remaining))

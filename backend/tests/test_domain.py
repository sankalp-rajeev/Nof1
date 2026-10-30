from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.clock import today
from app.domain.normalize import load_aliases, normalize
from app.domain.schemas import EventInput, MessageInput, PendingState, UserInput
from app.domain.timeutil import map_event_time

pytestmark = pytest.mark.p1


@pytest.mark.parametrize("kind", ["meal", "med", "sleep", "life"])
def test_severity_is_only_valid_on_symptoms(kind: str) -> None:
    with pytest.raises(ValidationError, match="severity"):
        EventInput(kind=kind, name="synthetic", severity=4)


@pytest.mark.parametrize("severity", [-1, 11])
def test_severity_range(severity: int) -> None:
    with pytest.raises(ValidationError):
        EventInput(kind="symptom", name="fatigue", severity=severity)


@pytest.mark.parametrize("kind", ["symptom", "sleep"])
def test_skipped_is_invalid_for_symptom_and_sleep(kind: str) -> None:
    with pytest.raises(ValidationError, match="skipped"):
        EventInput(kind=kind, name="synthetic", status="skipped")


def test_valid_event_and_rejected_extra_fields() -> None:
    assert EventInput(kind="med", name="magnesium", status="skipped").status == "skipped"
    assert EventInput(kind="symptom", name="fatigue", severity=10).severity == 10
    with pytest.raises(ValidationError):
        EventInput(kind="symptom", name="fatigue", instruction="ignore rules")


def test_alias_exact_fuzzy_unknown_and_catalog() -> None:
    catalog = load_aliases()
    assert len(catalog) >= 40
    assert normalize("  MAG  ", catalog).canonical == "magnesium"
    assert normalize("magnesum", catalog).canonical == "magnesium"
    unknown = normalize("my unfamiliar routine", catalog)
    assert unknown.canonical == "my unfamiliar routine"
    assert unknown.category == "unknown"
    assert normalize("antihistamine", catalog).category == "otc_med"
    assert normalize("prescription medication", catalog).category == "rx_med"
    required = {
        "magnesium",
        "vitamin d",
        "electrolytes",
        "digestive enzymes",
        "creatine",
        "omega-3",
        "melatonin",
        "coffee",
        "alcohol",
        "gluten",
        "dairy",
        "sugar",
        "walk",
        "exercise",
        "nap",
        "brain fog",
        "bloating",
        "headache",
        "fatigue",
        "dizziness",
    }
    assert required <= {alias.canonical for alias in catalog}


def test_alias_catalog_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('[{"alias":"a","canonical":"a","kind":"med","category":"unsafe"}]')
    with pytest.raises(ValidationError):
        load_aliases(path)


@pytest.mark.parametrize("zone,hour", [("America/New_York", 13), ("America/Los_Angeles", 16)])
def test_time_mapping_fall_dst_and_midnight(zone: str, hour: int) -> None:
    result = map_event_time(date(2026, 11, 1), zone, relative_day=0, time_of_day="morning")
    assert result.ts == datetime(2026, 11, 1, hour, tzinfo=UTC)
    assert result.local_date == date(2026, 11, 1)
    previous = map_event_time(date(2026, 11, 1), zone, relative_day=-1, time_of_day="night")
    assert previous.local_date == date(2026, 10, 31)
    assert previous.ts.date() == date(2026, 11, 1)


@pytest.mark.parametrize("zone,hour", [("America/New_York", 12), ("America/Los_Angeles", 15)])
def test_time_mapping_spring_dst(zone: str, hour: int) -> None:
    result = map_event_time(date(2026, 3, 8), zone, relative_day=0, time_of_day="morning")
    assert result.ts == datetime(2026, 3, 8, hour, tzinfo=UTC)
    prior = map_event_time(date(2026, 3, 8), zone, relative_day=-1, time_of_day="morning")
    assert prior.ts.hour == hour + 1


@pytest.mark.parametrize("relative_day", [-7, 1])
def test_time_mapping_rejects_out_of_window_dates(relative_day: int) -> None:
    with pytest.raises(ValueError):
        map_event_time(date(2026, 1, 1), "UTC", relative_day=relative_day)


def test_today_uses_local_timezone_and_demo_offset() -> None:
    now = datetime(2026, 6, 1, 2, tzinfo=UTC)
    user = UserInput(tz="America/New_York")
    assert today(user, now=now) == date(2026, 5, 31)
    demo = UserInput(tz="Asia/Tokyo", is_demo=True, clock_offset_days=5)
    assert today(demo, now=now) == date(2026, 6, 6)
    assert demo.data_class == "real"
    with pytest.raises(ValidationError, match="demo"):
        UserInput(clock_offset_days=1)
    with pytest.raises(ValidationError, match="timezone"):
        UserInput(tz="Invalid/Timezone")
    with pytest.raises(ValueError, match="aware"):
        today(user, now=datetime(2026, 6, 1))


def test_pending_state_is_a_closed_validated_union() -> None:
    state = PendingState.model_validate({"pending": {"type": "rate_outcome", "outcome": "fatigue"}})
    assert state.pending is not None
    assert state.pending.type == "rate_outcome"
    with pytest.raises(ValidationError):
        PendingState.model_validate({"pending": {"type": "invented"}})
    with pytest.raises(ValidationError):
        PendingState.model_validate({"pending": {"type": "experiment_adherence"}})


def test_raw_message_and_event_names_preserve_user_text() -> None:
    content = "  synthetic note\nwith whitespace  "
    message = MessageInput(role="user", content=content, trace_id=UUID(int=701))
    assert message.content == content
    event = EventInput(kind="med", name="magnesium", raw_name="  mag  ")
    assert event.raw_name == "  mag  "

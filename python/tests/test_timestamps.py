"""`format: date-time` and `format: date-time-local` fields accept the RFC 3339 forms only.

See `power_openapi_models/timestamps.py` for why the pydantic types are not used directly.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

import power_openapi_models
from power_openapi_models.infrastructure_core.models import DataSource
from power_openapi_models.timeseries.models import SingleTimeSeries
from power_openapi_models.timestamps import LocalDatetime, OffsetDatetime

OFFSET = TypeAdapter(OffsetDatetime)
LOCAL = TypeAdapter(LocalDatetime)

NOT_RFC3339 = [
    "2024-01-01",
    "not a timestamp",
    "",
    "2024-13-01T00:00:00Z",
    "2024-01-01 00:00:00Z",
    "2024-01-01t00:00:00z",
    "2024-01-01T00:00Z",
    "2024-01-01T00:00:00.123456Z",
    "2024-01-01T00:00:00+0200",
    "2024-01-01T00:00:00Z\n",
    "1704067200",
]


@pytest.mark.parametrize(
    "written",
    ["2024-01-01T00:00:00Z", "2024-01-01T02:00:00+02:00", "2024-01-01T00:00:00.250-07:00"],
)
def test_offset_form_round_trips(written):
    value = OFFSET.validate_python(written)
    assert value.tzinfo is not None
    assert OFFSET.dump_python(value, mode="json") == written


def test_offset_keeps_the_offset_and_writes_z_for_zero():
    plus = OFFSET.validate_python("2024-01-01T02:00:00+02:00")
    assert plus.utcoffset() == timedelta(hours=2)
    assert plus == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert OFFSET.dump_python(OFFSET.validate_python("2024-01-01T00:00:00+00:00"), mode="json") == (
        "2024-01-01T00:00:00Z"
    )


@pytest.mark.parametrize("bad", [*NOT_RFC3339, "2024-01-01T00:00:00", 1704067200])
def test_offset_rejects_everything_else(bad):
    with pytest.raises(ValidationError):
        OFFSET.validate_python(bad)


@pytest.mark.parametrize("written", ["2024-01-01T00:00:00", "2024-01-01T00:00:00.250"])
def test_local_form_round_trips(written):
    value = LOCAL.validate_python(written)
    assert value.tzinfo is None
    assert LOCAL.dump_python(value, mode="json") == written


@pytest.mark.parametrize(
    "bad",
    [*NOT_RFC3339, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00+02:00", "2024-01-01 00:00:00"],
)
def test_local_rejects_everything_else(bad):
    with pytest.raises(ValidationError):
        LOCAL.validate_python(bad)


def test_datetime_objects_need_millisecond_precision():
    assert OFFSET.validate_python(datetime(2024, 1, 1, microsecond=250_000, tzinfo=timezone.utc))
    assert LOCAL.validate_python(datetime(2024, 1, 1))
    with pytest.raises(ValidationError):
        OFFSET.validate_python(datetime(2024, 1, 1, microsecond=1, tzinfo=timezone.utc))
    with pytest.raises(ValidationError):
        LOCAL.validate_python(datetime(2024, 1, 1, tzinfo=timezone.utc))


def test_data_source_timestamps_need_an_offset():
    base = {"id": 1, "fields": [], "retrieved_at": "2024-01-01T00:00:00Z"}
    source = DataSource.model_validate({**base, "published_at": None})
    assert source.retrieved_at.utcoffset() == timedelta(0)
    assert source.published_at is None
    with pytest.raises(ValidationError):
        DataSource.model_validate({**base, "retrieved_at": "2024-01-01T00:00:00"})
    with pytest.raises(ValidationError):
        DataSource.model_validate({**base, "published_at": "2024-02-01T00:00:00"})


def _series(timestamp):
    return {
        "association_id": 1,
        "owner_id": 2,
        "owner_type": "ACBus",
        "owner_category": "Component",
        "time_series_type": "SingleTimeSeries",
        "name": "max_active_power",
        "features": {},
        "uri": "abc123",
        "element_type": "f64",
        "element_shape": [],
        "initial_timestamp": timestamp,
        "resolution": "PT1H",
        "length": 24,
    }


def test_series_timestamp_with_an_offset():
    parsed = SingleTimeSeries.model_validate(_series("2024-01-01T02:00:00+02:00"))
    assert parsed.initial_timestamp.utcoffset() == timedelta(hours=2)
    dumped = parsed.model_dump(mode="json", exclude_unset=True)
    assert dumped["initial_timestamp"] == "2024-01-01T02:00:00+02:00"


def _schema_at_least(major, minor):
    parts = power_openapi_models.__schema_version__.lstrip("v").split(".")
    return (int(parts[0]), int(parts[1])) >= (major, minor)


@pytest.mark.skipif(
    not _schema_at_least(0, 4), reason="schema 0.4.0 added date-time-local series timestamps"
)
def test_series_timestamp_without_an_offset_stays_a_wall_clock():
    parsed = SingleTimeSeries.model_validate(_series("2024-01-01T00:00:00"))
    assert parsed.initial_timestamp == datetime(2024, 1, 1)
    assert parsed.initial_timestamp.tzinfo is None
    dumped = parsed.model_dump(mode="json", exclude_unset=True)
    assert dumped["initial_timestamp"] == "2024-01-01T00:00:00"

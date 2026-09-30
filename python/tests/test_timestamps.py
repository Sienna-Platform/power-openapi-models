"""`format: date-time` fields accept a timestamp with no offset, read as UTC.

Behaviour shared with the TypeScript and Rust packages; see
`power_openapi_models/timestamps.py` for why.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from power_openapi_models.infrastructure_core.models import DataSource
from power_openapi_models.timeseries.models import SingleTimeSeries


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


def test_naive_timestamp_is_read_as_utc():
    parsed = SingleTimeSeries.model_validate(_series("2024-01-01T00:00:00"))
    assert parsed.initial_timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert parsed.initial_timestamp.utcoffset() == timedelta(0)


def test_naive_fractional_seconds():
    parsed = SingleTimeSeries.model_validate(_series("2024-01-01T00:00:00.250"))
    assert parsed.initial_timestamp.microsecond == 250_000


def test_z_and_offsets_are_kept():
    z = SingleTimeSeries.model_validate(_series("2024-01-01T00:00:00Z"))
    assert z.initial_timestamp.utcoffset() == timedelta(0)
    plus = SingleTimeSeries.model_validate(_series("2024-01-01T02:00:00+02:00"))
    assert plus.initial_timestamp.utcoffset() == timedelta(hours=2)
    assert plus.initial_timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_naive_datetime_object_is_read_as_utc():
    parsed = SingleTimeSeries.model_validate(_series(datetime(2024, 1, 1)))
    assert parsed.initial_timestamp.tzinfo is timezone.utc


@pytest.mark.parametrize("bad", ["2024-01-01", "not a timestamp", "", "2024-13-01T00:00:00"])
def test_non_timestamps_are_still_rejected(bad):
    with pytest.raises(ValidationError):
        SingleTimeSeries.model_validate(_series(bad))


def test_written_timestamp_always_carries_an_offset():
    dumped = SingleTimeSeries.model_validate(_series("2024-01-01T00:00:00")).model_dump(mode="json")
    assert dumped["initial_timestamp"] == "2024-01-01T00:00:00Z"


def test_nullable_timestamp_field():
    base = {"id": 1, "fields": [], "retrieved_at": "2024-01-01T00:00:00"}
    fields = DataSource.model_fields
    assert "retrieved_at" in fields and "published_at" in fields
    naive = DataSource.model_validate({**base, "published_at": "2024-02-01T00:00:00"})
    assert naive.published_at.tzinfo is timezone.utc
    assert DataSource.model_validate({**base, "published_at": None}).published_at is None

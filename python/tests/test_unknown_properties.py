"""A model rejects a property its schema does not list, as the strict bundles
and the TypeScript and Rust packages do. A map schema stays open."""

import pytest
from pydantic import ValidationError

from power_openapi_models.timeseries.models import SingleTimeSeries


def _series(**extra):
    return {
        "association_id": 1,
        "owner_id": 2,
        "owner_type": "ACBus",
        "owner_category": "Component",
        "time_series_type": "SingleTimeSeries",
        "name": "max_active_power",
        "features": {"scenario": "high", "model_year": 2030},
        "uri": "abc123",
        "element_type": "f64",
        "element_shape": [],
        "initial_timestamp": "2024-01-01T00:00:00Z",
        "resolution": "PT1H",
        "length": 24,
        **extra,
    }


def test_unknown_property_is_rejected():
    with pytest.raises(ValidationError, match="owner_typ"):
        SingleTimeSeries.model_validate(_series(owner_typ="Typo"))


def test_map_schema_accepts_any_key():
    parsed = SingleTimeSeries.model_validate(_series())
    assert set(parsed.features.root) == {"scenario", "model_year"}

"""No generated model fills a schema default.

The SDK contract (see the README): a schema `default` documents the value a consumer
assumes for an absent field; no SDK inserts it. An omitted optional field stays `None`, and
a schema-required field stays required even with a default, as in the Julia package. The
one exception is a `const` field, such as a discriminator: the schema fixes its value.
"""

import importlib
import inspect
import typing

import pytest
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

DOMAINS = ["infrastructure_core", "core", "operations", "investments", "dynamics", "timeseries"]


def _filled_defaults():
    for domain in DOMAINS:
        module = importlib.import_module(f"power_openapi_models.{domain}.models")
        for name, cls in vars(module).items():
            if not (inspect.isclass(cls) and issubclass(cls, BaseModel)):
                continue
            if cls.__module__ != module.__name__:
                continue
            for field, info in cls.model_fields.items():
                if info.default in (None, PydanticUndefined) and info.default_factory is None:
                    continue
                if typing.get_origin(info.annotation) is typing.Literal:
                    continue
                yield f"{name}.{field} = {info.default!r}"


def test_no_model_fills_a_schema_default():
    assert list(_filled_defaults()) == []


def test_an_omitted_field_stays_absent():
    from power_openapi_models.timeseries.models import SingleTimeSeries

    series = SingleTimeSeries.model_validate(
        {
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
            "initial_timestamp": "2024-01-01T00:00:00Z",
            "resolution": "PT1H",
            "length": 24,
        }
    )
    assert series.interval_alignment is None
    assert "interval_alignment" not in series.model_dump(mode="json", exclude_unset=True)


@pytest.mark.parametrize("missing", ["vom_cost", "power_units"])
def test_a_required_field_with_a_default_stays_required(missing):
    from power_openapi_models.core.models import CostCurve

    curve = {
        "value_curve": {
            "curve_type": "INPUT_OUTPUT",
            "function_data": {
                "function_type": "LINEAR",
                "proportional_term": 1.0,
                "constant_term": 0.0,
            },
        },
        "vom_cost": {
            "curve_type": "INPUT_OUTPUT",
            "function_data": {
                "function_type": "LINEAR",
                "proportional_term": 0.0,
                "constant_term": 0.0,
            },
        },
        "power_units": "NATURAL_UNITS",
    }
    CostCurve.model_validate(curve)
    del curve[missing]
    with pytest.raises(ValueError):
        CostCurve.model_validate(curve)

"""A defaulted enum field holds the enum member, as a validated value does.

pydantic does not validate a default, so a string default left a `str` in an enum field, and
`model_dump(mode="json")` warned `PydanticSerializationUnexpectedValue`. The Makefile passes
`--set-default-enum-member` to datamodel-codegen.
"""

import enum
import importlib
import inspect
import typing
import warnings

import pytest
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from power_openapi_models.timeseries.models import SingleTimeSeries

DOMAINS = ["infrastructure_core", "core", "operations", "investments", "dynamics", "timeseries"]


def _enums(annotation):
    if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):
        yield annotation
    for arg in typing.get_args(annotation):
        yield from _enums(arg)


def _enum_defaults():
    for domain in DOMAINS:
        module = importlib.import_module(f"power_openapi_models.{domain}.models")
        for name, cls in vars(module).items():
            if not (inspect.isclass(cls) and issubclass(cls, BaseModel)):
                continue
            if cls.__module__ != module.__name__:
                continue
            for field, info in cls.model_fields.items():
                enums = tuple(_enums(info.annotation))
                if enums and info.default not in (None, PydanticUndefined):
                    yield pytest.param(info.default, enums, id=f"{name}.{field}")


@pytest.mark.parametrize(("default", "enums"), list(_enum_defaults()))
def test_enum_default_is_a_member(default, enums):
    assert isinstance(default, enums)


def test_dumping_a_defaulted_enum_does_not_warn():
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
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert series.model_dump(mode="json")["interval_alignment"] == "PERIOD_ENDING"

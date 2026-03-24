"""Basic import tests for generated models."""

import json
import pytest


def test_import_package():
    """Verify the main package imports without error."""
    import power_openapi_models

    assert hasattr(power_openapi_models, "core")
    assert hasattr(power_openapi_models, "operations")
    assert hasattr(power_openapi_models, "investments")
    assert hasattr(power_openapi_models, "dynamics")


def test_import_core_models():
    """Verify core models can be imported."""
    from power_openapi_models.core import models

    assert hasattr(models, "MinMax")
    assert hasattr(models, "UpDown")
    assert hasattr(models, "FunctionData")


def test_import_operations_models():
    """Verify operations models can be imported."""
    from power_openapi_models.operations import models

    assert hasattr(models, "AcBus") or hasattr(models, "ACBus")


def test_simple_model_roundtrip():
    """MinMax should serialize and deserialize correctly."""
    from power_openapi_models.core.models import MinMax

    original = MinMax(min=0.0, max=100.0)
    json_str = original.model_dump_json()
    restored = MinMax.model_validate_json(json_str)
    assert restored.min == original.min
    assert restored.max == original.max


def test_discriminated_union():
    """FunctionData should use discriminator-based dispatch."""
    from power_openapi_models.core.models import (
        FunctionData,
        LinearFunctionData,
        QuadraticFunctionData,
    )

    linear_json = json.dumps({
        "function_type": "LINEAR",
        "proportional_term": 2.0,
        "constant_term": 5.0,
    })
    result = FunctionData.model_validate_json(linear_json)
    assert isinstance(result.root, LinearFunctionData)
    assert result.root.proportional_term == 2.0

    quad_json = json.dumps({
        "function_type": "QUADRATIC",
        "quadratic_term": 1.0,
        "proportional_term": 2.0,
        "constant_term": 0.0,
    })
    result = FunctionData.model_validate_json(quad_json)
    assert isinstance(result.root, QuadraticFunctionData)
    assert result.root.quadratic_term == 1.0


def test_nested_discriminated_union():
    """InputOutputCurve with nested discriminated function_data."""
    from power_openapi_models.core.models import InputOutputCurve

    data = {
        "curve_type": "INPUT_OUTPUT",
        "function_data": {
            "function_type": "LINEAR",
            "proportional_term": 1.5,
            "constant_term": 10.0,
        },
    }
    curve = InputOutputCurve.model_validate(data)
    assert curve.function_data.proportional_term == 1.5

    roundtripped = InputOutputCurve.model_validate_json(curve.model_dump_json())
    assert roundtripped.function_data.proportional_term == 1.5


def test_enum_validation():
    """Literal discriminator fields reject invalid values."""
    from power_openapi_models.core.models import LinearFunctionData
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LinearFunctionData(
            function_type="INVALID",
            proportional_term=1.0,
            constant_term=0.0,
        )

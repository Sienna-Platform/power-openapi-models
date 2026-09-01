"""Tests for the hand-written SystemDocument container (src/power_openapi_models/document.py).

`document.py` is loaded standalone via importlib rather than through the normal
`power_openapi_models` package import: today's regenerated `core/models.py` dropped
`ComplexNumber`, which `operations/models.py` still imports, so importing anything under
`power_openapi_models` currently raises ImportError. That gap is tracked elsewhere; this
test file works around it rather than fixing it, the same way `document.py` itself falls
back to `list[dict]` for the association fields it cannot import.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT.parent / "SiennaSchemas" / "Core" / "SystemDocument.json"


def _load_document_module():
    spec = importlib.util.spec_from_file_location(
        "power_openapi_models.document",
        REPO_ROOT / "src" / "power_openapi_models" / "document.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def document_module():
    return _load_document_module()


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


def test_field_set_matches_schema_properties(document_module, schema):
    model_fields = set(document_module.SystemDocument.model_fields)
    schema_properties = set(schema["properties"])
    assert model_fields == schema_properties


def test_required_fields_match_schema_required(document_module, schema):
    required = {
        name
        for name, field in document_module.SystemDocument.model_fields.items()
        if field.is_required()
    }
    assert required == set(schema["required"])


def test_trading_hub_associations_defaults_to_empty_list(document_module, schema):
    field = document_module.SystemDocument.model_fields["trading_hub_associations"]
    assert (
        field.default_factory()
        == schema["properties"]["trading_hub_associations"]["default"]
        == []
    )


def test_rejects_top_level_unit_system_and_base_power(document_module):
    minimal = {
        "components": {},
        "supplemental_attributes": [],
        "supplemental_attribute_associations": [],
        "plant_associations": [],
        "combined_cycle_associations": [],
        "service_associations": [],
        "time_series_associations": [],
        "time_series_storage_file": None,
    }
    with pytest.raises(ValidationError):
        document_module.SystemDocument.model_validate(
            {**minimal, "unit_system": "NATURAL_UNITS"}
        )
    with pytest.raises(ValidationError):
        document_module.SystemDocument.model_validate({**minimal, "base_power": 100.0})


def test_write_read_roundtrip(document_module, tmp_path):
    doc = document_module.SystemDocument(
        name="minimal system",
        description=None,
        frequency=60.0,
        components={
            "ACBus": [{"id": 1, "name": "bus1"}],
            "ThermalStandard": [{"id": 2, "name": "gen1"}],
        },
        supplemental_attributes=[{"id": 3}],
        supplemental_attribute_associations=[
            {
                "component_id": 1,
                "component_type": "ACBus",
                "attribute_id": 3,
                "attribute_type": "GeographicInfo",
            }
        ],
        plant_associations=[],
        combined_cycle_associations=[],
        service_associations=[],
        trading_hub_associations=[],
        time_series_associations=[],
        ext={},
        time_series_storage_file=None,
    )

    out_path = tmp_path / "document.json"
    document_module.write_document(doc, out_path)
    reloaded = document_module.read_document(out_path)

    assert reloaded == doc


def test_write_document_sorts_component_keys(document_module, tmp_path):
    doc = document_module.SystemDocument(
        components={
            "ThermalStandard": [{"id": 2}],
            "ACBus": [{"id": 1}],
        },
        supplemental_attributes=[],
        supplemental_attribute_associations=[],
        plant_associations=[],
        combined_cycle_associations=[],
        service_associations=[],
        time_series_associations=[],
        time_series_storage_file=None,
    )
    out_path = tmp_path / "document.json"
    document_module.write_document(doc, out_path)

    raw = json.loads(out_path.read_text())
    assert list(raw["components"].keys()) == ["ACBus", "ThermalStandard"]

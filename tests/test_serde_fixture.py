"""Serde tests against real 14-bus operations documents.

Fixtures are byte-identical copies of PowerFlowFileParser-emitted 14-bus
documents vendored from SiennaSchemas, kept in sync with a sibling Julia-side
fixture test. Operations types only, no time series.
"""

import json
from pathlib import Path

import pytest

from power_openapi_models.core import models as core_models
from power_openapi_models.operations import models as operations_models

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXPECTED_COMPONENT_COUNT = 119

# Mirrors Core/SystemDocument.json's `required`/optional keys
# (see scripts/check_json_compat.py, which this test's comparison logic follows).
REQUIRED_ENVELOPE_KEYS = {
    "base_power",
    "unit_system",
    "components",
    "supplemental_attributes",
    "supplemental_attribute_associations",
    "time_series_associations",
    "time_series_storage_file",
}
OPTIONAL_ENVELOPE_KEYS = {"ext", "name", "description", "frequency"}
ENVELOPE_KEYS = REQUIRED_ENVELOPE_KEYS | OPTIONAL_ENVELOPE_KEYS


def _registry():
    """type name -> pydantic class, across the domains these fixtures use."""
    registry = {}
    for module in (core_models, operations_models):
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and hasattr(obj, "model_fields"):
                registry.setdefault(attr, obj)
    return registry


def _strip_none(value):
    """Drop None-valued keys so an omitted field and an explicit null compare equal."""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


def _diff(before, after, path=""):
    """Field-level differences between two payloads, as human-readable strings."""
    out = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            here = f"{path}.{key}" if path else key
            if key not in after:
                out.append(f"dropped {here} (was {before[key]!r})")
            elif key not in before:
                out.append(f"added {here} = {after[key]!r}")
            else:
                out.extend(_diff(before[key], after[key], here))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            out.append(f"length {path}: {len(before)} -> {len(after)}")
        else:
            for i, (b, a) in enumerate(zip(before, after)):
                out.extend(_diff(b, a, f"{path}[{i}]"))
    elif before != after:
        out.append(f"changed {path}: {before!r} -> {after!r}")
    return out


@pytest.fixture(params=["NATURAL_UNITS", "COMPONENT_BASE"])
def fixture_doc(request):
    path = FIXTURES_DIR / f"case14_operations.{request.param}.json"
    return json.loads(path.read_text())


def test_envelope_keys(fixture_doc):
    missing = REQUIRED_ENVELOPE_KEYS - set(fixture_doc)
    unexpected = set(fixture_doc) - ENVELOPE_KEYS
    assert not missing, f"missing envelope keys: {sorted(missing)}"
    assert not unexpected, f"unexpected envelope keys: {sorted(unexpected)}"


def test_component_count(fixture_doc):
    total = sum(len(entries) for entries in fixture_doc["components"].values())
    assert total == EXPECTED_COMPONENT_COUNT


def test_all_components_validate(fixture_doc):
    registry = _registry()
    for type_name, entries in fixture_doc["components"].items():
        assert type_name in registry, f"no generated model for {type_name!r}"
        cls = registry[type_name]
        for entry in entries:
            cls.model_validate(entry)


def test_roundtrip_no_field_drift(fixture_doc):
    registry = _registry()
    rebuilt = {}
    for type_name, entries in fixture_doc["components"].items():
        cls = registry[type_name]
        rebuilt[type_name] = [
            cls.model_validate(entry).model_dump(mode="json", by_alias=True)
            for entry in entries
        ]
    diffs = _diff(_strip_none(fixture_doc["components"]), _strip_none(rebuilt))
    assert not diffs, "\n".join(diffs[:20])


def test_natural_units_spot_checks():
    doc = json.loads(
        (FIXTURES_DIR / "case14_operations.NATURAL_UNITS.json").read_text()
    )
    assert doc["base_power"] == 100.0
    assert doc["unit_system"] == "NATURAL_UNITS"
    bus = doc["components"]["ACBus"][0]
    assert bus["base_voltage"] == 138.0
    assert len(doc["supplemental_attribute_associations"]) == 9


def test_component_base_spot_checks():
    doc = json.loads((FIXTURES_DIR / "case14_operations.COMPONENT_BASE.json").read_text())
    assert doc["base_power"] == 100.0
    assert doc["unit_system"] == "COMPONENT_BASE"
    bus = doc["components"]["ACBus"][0]
    assert bus["base_voltage"] == 138.0
    assert len(doc["supplemental_attribute_associations"]) == 9


def test_component_base_actually_converts_from_natural_units():
    """The two fixtures must differ in more than the ``unit_system`` tag.

    Neither spot-check test above reads both fixtures, so a COMPONENT_BASE fixture
    that is a byte-identical copy of NATURAL_UNITS would pass them both. A Line's
    ``rating`` (ApparentPower, MVA, no per-field unit-basis discriminator) is
    genuinely per-unit-on-own-``base_power`` in COMPONENT_BASE: assert that physical
    relationship directly, across every line, and that at least one line actually
    differs numerically.
    """
    natural = json.loads(
        (FIXTURES_DIR / "case14_operations.NATURAL_UNITS.json").read_text()
    )
    component = json.loads(
        (FIXTURES_DIR / "case14_operations.COMPONENT_BASE.json").read_text()
    )
    natural_lines = {c["id"]: c for c in natural["components"]["Line"]}
    component_lines = {c["id"]: c for c in component["components"]["Line"]}
    assert natural_lines.keys() == component_lines.keys()
    differed = 0
    for id_, nat in natural_lines.items():
        dev = component_lines[id_]
        assert dev["rating"] == pytest.approx(nat["rating"] / nat["base_power"])
        if dev["rating"] != nat["rating"]:
            differed += 1
    assert differed > 0

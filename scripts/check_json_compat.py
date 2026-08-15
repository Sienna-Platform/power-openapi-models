#!/usr/bin/env python3
"""Check that OpenAPI JSON documents are compatible in both directions.

  python3 scripts/check_json_compat.py
  python3 scripts/check_json_compat.py --input ../PowerFlowFileParser.jl/inspection_output
  python3 scripts/check_json_compat.py --skip-selftest

Two directions are checked.

**Julia -> Python.** Every document in the input directory is loaded, its envelope
keys are checked, and each entry under `components` is resolved to its generated
pydantic class by type name and validated. A document whose `components` map is
empty passes trivially: that is reported as VACUOUS rather than OK, because a
green result on an empty document says nothing about component compatibility.

**Python -> Julia.** What Python parsed is dumped back out and compared field by
field against the input, so a field the Python models silently drop, add, or
retype shows up. The re-emitted document is written next to the input as
`<name>.roundtrip.json` for the Julia side to read.

The self-test builds a small document from the generated models directly, so the
comparison machinery is exercised even while PowerFlowFileParser's emit layer is
unimplemented and its documents carry no components. Exits non-zero if any check
fails, so this is usable as a gate.
"""

import argparse
import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / ".." / "PowerFlowFileParser.jl" / "inspection_output"
DOMAINS = ("core", "operations", "investments", "dynamics")
# Mirrors Core/SystemDocument.json's `required` list.
REQUIRED_ENVELOPE_KEYS = {
    "base_power",
    "unit_system",
    "components",
    "supplemental_attributes",
    "supplemental_attribute_associations",
    "time_series_associations",
    "time_series_storage_file",
}
# Properties the schema declares but does not require (absent is valid, not a gap).
OPTIONAL_ENVELOPE_KEYS = {"ext", "name", "description", "frequency"}
ENVELOPE_KEYS = REQUIRED_ENVELOPE_KEYS | OPTIONAL_ENVELOPE_KEYS


def load_domains():
    """Map type name -> (domain, pydantic class) across every generated module."""
    registry = {}
    for domain in DOMAINS:
        module = importlib.import_module(f"power_openapi_models.{domain}.models")
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and hasattr(obj, "model_fields"):
                registry.setdefault(attr, (domain, obj))
    return registry


def strip_none(value):
    """Drop None-valued keys so an omitted field and an explicit null compare equal.

    The Julia serializer omits unset fields entirely, while pydantic materializes
    them as None, so without this every optional field would read as a difference.
    """
    if isinstance(value, dict):
        return {k: strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [strip_none(v) for v in value]
    return value


def diff_payload(before, after, path=""):
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
                out.extend(diff_payload(before[key], after[key], here))
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            out.append(f"length {path}: {len(before)} -> {len(after)}")
        else:
            for i, (b, a) in enumerate(zip(before, after)):
                out.extend(diff_payload(b, a, f"{path}[{i}]"))
    elif before != after:
        out.append(f"changed {path}: {before!r} -> {after!r}")
    return out


def check_document(path, registry):
    """Validate one document both ways. Returns (status, messages)."""
    messages = []
    raw = json.loads(path.read_text())

    missing = REQUIRED_ENVELOPE_KEYS - set(raw)
    unexpected = set(raw) - ENVELOPE_KEYS
    if missing:
        messages.append(f"envelope missing keys: {sorted(missing)}")
    if unexpected:
        messages.append(f"envelope has unexpected keys: {sorted(unexpected)}")

    components = raw.get("components") or {}
    validated = {}
    total = 0
    for type_name, entries in sorted(components.items()):
        if type_name not in registry:
            messages.append(f"no generated model for component type {type_name!r}")
            continue
        domain, cls = registry[type_name]
        rebuilt = []
        for i, entry in enumerate(entries):
            try:
                model = cls.model_validate(entry)
            except Exception as exc:  # pydantic ValidationError and friends
                first = str(exc).splitlines()
                messages.append(f"{type_name}[{i}] rejected: {' | '.join(first[:3])}")
                continue
            rebuilt.append(model.model_dump(mode="json", by_alias=True))
            total += 1
        validated[type_name] = rebuilt

    # Python -> Julia: re-emit and compare against what came in.
    roundtrip = dict(raw)
    roundtrip["components"] = validated
    diffs = diff_payload(strip_none(components), strip_none(validated))
    for d in diffs[:12]:
        messages.append(f"roundtrip: {d}")
    if len(diffs) > 12:
        messages.append(f"roundtrip: ...and {len(diffs) - 12} more differences")

    out_path = path.with_suffix(".roundtrip.json")
    out_path.write_text(json.dumps(roundtrip, indent=2, sort_keys=True))

    if messages:
        return "FAIL", messages, total
    if total == 0:
        return "VACUOUS", ["components map is empty — nothing to validate"], 0
    return "OK", [], total


def selftest(registry, out_dir):
    """Build a document from the models, then read it back, proving both directions."""
    core = importlib.import_module("power_openapi_models.core.models")
    ops = importlib.import_module("power_openapi_models.operations.models")

    buses = [
        ops.ACBus(id=1, number=101, name="BUS101", available=True, base_voltage=138.0),
        ops.ACBus(id=2, number=102, name="BUS102", available=True, base_voltage=138.0),
    ]
    shunt = ops.FixedAdmittance(
        id=3,
        name="SHUNT102",
        available=True,
        bus=2,
        Y=core.ComplexNumber(real=0.5, imag=-3.0),
    )
    document = {
        "base_power": 100.0,
        "unit_system": "NATURAL_UNITS",
        "components": {
            "ACBus": [b.model_dump(mode="json", by_alias=True) for b in buses],
            "FixedAdmittance": [shunt.model_dump(mode="json", by_alias=True)],
        },
        "supplemental_attributes": [],
        "supplemental_attribute_associations": [
            core.SupplementalAttributeAssociation(
                attribute_id=1, entity_id=2, attribute_type="GeographicInfo"
            ).model_dump(mode="json", by_alias=True)
        ],
        "time_series_associations": [],
        "time_series_storage_file": None,
    }
    path = out_dir / "python_authored_selftest.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True))

    status, messages, total = check_document(path, registry)
    return status, messages, total, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT),
                        help="directory of OpenAPI JSON documents (default: PFFP inspection_output)")
    parser.add_argument("--skip-selftest", action="store_true",
                        help="only check documents found in --input")
    args = parser.parse_args()

    registry = load_domains()
    print(f"Generated models: {len(registry)} types across {', '.join(DOMAINS)}\n")

    failures = 0
    in_dir = Path(args.input).resolve()

    if not args.skip_selftest:
        out_dir = in_dir if in_dir.is_dir() else REPO_ROOT
        out_dir.mkdir(parents=True, exist_ok=True)
        status, messages, total, path = selftest(registry, out_dir)
        print(f"[self-test] {status}  ({total} components validated)  -> {path.name}")
        for m in messages:
            print(f"    {m}")
        if status == "FAIL":
            failures += 1
        print()

    if not in_dir.is_dir():
        print(f"Input directory not found: {in_dir}")
        print("Generate documents first:")
        print("  cd ../PowerFlowFileParser.jl && julia --project scripts/inspect_14bus_json.jl")
        return 1 if failures else 0

    docs = sorted(
        p for p in in_dir.glob("*.json")
        if not p.name.endswith((".roundtrip.json", ".pm.json"))
        and p.name != "python_authored_selftest.json"
    )
    if not docs:
        print(f"No OpenAPI documents in {in_dir} (looked for *.json, excluding *.pm.json)")
        return 1 if failures else 0

    for path in docs:
        status, messages, total = check_document(path, registry)
        print(f"[{status}] {path.name}  ({total} components validated)")
        for m in messages:
            print(f"    {m}")
        if status == "FAIL":
            failures += 1

    print()
    if failures:
        print(f"{failures} document(s) failed compatibility.")
        return 1
    print("All documents compatible in both directions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

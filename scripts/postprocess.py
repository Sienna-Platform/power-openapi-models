#!/usr/bin/env python3
"""Post-process generated models to fix known datamodel-codegen issues.

Each fix targets a specific known problem. New issues should be added as
separate fix functions. When an upstream fix lands, the corresponding
function can be removed.

After applying fixes, the script scans for potential new issues and warns
about them without attempting an automatic fix.
"""

import re
import sys
from pathlib import Path

PKG_DIR = Path(__file__).parent.parent / "src" / "power_openapi_models"

PRIMITIVES = {"float", "int", "str", "bool"}


# ---------------------------------------------------------------------------
# Fixes — each function takes file content and returns (modified_content, bool)
# where the bool indicates whether a change was made.
# ---------------------------------------------------------------------------


def fix_thermal_generation_cost_start_up(content: str) -> tuple[str, bool]:
    """Remove discriminator from ThermalGenerationCost.start_up field.

    datamodel-codegen emits discriminator="startup_stages_type" on the
    start_up field, but its type is ``float | StartUpStages``. Pydantic
    requires all discriminated-union variants to be BaseModel subclasses,
    so the discriminator must be removed.
    """
    fixed = re.sub(
        r'(start_up: float \| StartUpStages = Field\([^)]*?)'
        r',\s*discriminator="startup_stages_type"',
        r'\1',
        content,
        flags=re.DOTALL,
    )
    return fixed, fixed != content


INPUT_OUTPUT_CURVE_ZERO_DEFAULT = """{
            "curve_type": "INPUT_OUTPUT",
            "function_data": {
                "function_type": "LINEAR",
                "constant_term": 0,
                "proportional_term": 0,
            },
        }"""

# (unique description substring, field name, type) -> the JSON-literal default
# that should replace the bare `None` datamodel-codegen emitted.
MISSING_TYPE_LEVEL_DEFAULTS = {
    "Linear or quadratic loss function with respect to the converter current.": (
        "loss_function",
        "InputOutputCurve",
    ),
    "Loss model coefficients. It accepts a linear model with a constant loss "
    "and a proportional loss rate (MW of loss per MW of flow). It also "
    "accepts a Piecewise loss, with N segments to specify different "
    "proportional losses for different segments.": ("loss", "TwoTerminalLoss"),
}


def fix_missing_composite_defaults(content: str) -> tuple[str, bool]:
    """Materialize a $ref field's type-level default when the property omits it.

    `InputOutputCurve` and `TwoTerminalLoss` each carry their own top-level
    `default` in the schema. Every *other* property that references them
    bare (e.g. `TwoTerminalLCCLine.loss`, `CostCurve.vom_cost`) repeats that
    default at the property level, so datamodel-codegen picks it up directly.
    `InterconnectingConverter.loss_function` and `TwoTerminalGenericHVDCLine.loss`
    are the two exceptions — they reference the type with no property-level
    default. SiennaSchemas' spec bundler inlines a bare `$ref`'s target
    schema (including its default) at the usage site, so the Julia side
    (which reads the bundled spec) picks it up; datamodel-codegen resolves
    `$ref`s from the unbundled spec and does not inherit a sibling-less
    type's own default, so it falls back to `None`. This restores parity
    with the value both the bundled spec and the Julia side already agree
    on, without touching SiennaSchemas.
    """
    changed = False
    for description, (field, type_name) in MISSING_TYPE_LEVEL_DEFAULTS.items():
        pattern = re.compile(
            rf'(    {re.escape(field)}: {re.escape(type_name)} \| None = Field\(\n)'
            rf"(        None,\n)"
            rf'(        description="{re.escape(description)}",\n    \))'
        )
        new_content, n = pattern.subn(
            rf"\1        {INPUT_OUTPUT_CURVE_ZERO_DEFAULT},\n\3", content
        )
        if n:
            content = new_content
            changed = True
    return content, changed


def fix_costcurve_power_units_default(content: str) -> tuple[str, bool]:
    """Restore `CostCurve.power_units`'s schema default, dropped by datamodel-codegen.

    `CostCurve.power_units` is schema-`required` *and* schema-`default:
    NATURAL_UNITS` (Core/common.json). Julia's `@kwdef` constructor honors
    the field-level default regardless of the required-list, so omitting
    `power_units` is harmless there. datamodel-codegen drops the default
    entirely for this required-with-default enum $ref (unlike the sibling
    `variable_cost_type`/`vom_cost` fields on the same model, which keep
    theirs), so any literal that omits `power_units` — including
    `CostCurve`'s own embedded defaults on `RenewableGenerationCost.
    curtailment_cost`, `MarketBidCost.incremental_offer_curves`, et al. —
    raises `ValidationError` on first use instead of falling back like
    Julia does. Only `CostCurve` itself (not `FuelCurve`, whose schema
    `power_units` has no sibling default) is affected.
    """
    pattern = re.compile(
        r"(class CostCurve\(BaseModel\):\n)(    power_units: UnitSystem\n)"
    )
    new_content, n = pattern.subn(
        r"\1    power_units: UnitSystem = UnitSystem.NATURAL_UNITS\n", content
    )
    return new_content, n > 0


FIXES = [
    fix_thermal_generation_cost_start_up,
    fix_missing_composite_defaults,
    fix_costcurve_power_units_default,
]


# ---------------------------------------------------------------------------
# Warnings — detect potential new issues without fixing them.
# ---------------------------------------------------------------------------


def _has_primitive_in_union(type_str: str) -> bool:
    parts = [p.strip() for p in type_str.split("|")]
    return any(p in PRIMITIVES for p in parts)


def warn_primitive_discriminators(content: str, path: Path) -> int:
    """Warn about any discriminated union field that includes a primitive type.

    This catches new instances of the same class of bug so they can be
    addressed with a targeted fix.
    """
    warnings = 0
    for match in re.finditer(
        r"^\s+(\w+):\s*(.+?)\s*=\s*Field\(", content, re.MULTILINE
    ):
        field_name = match.group(1)
        type_str = match.group(2)
        if not _has_primitive_in_union(type_str):
            continue
        # The discriminator must belong to this Field() call, not a later one.
        paren_end = content.find(")", match.start())
        if paren_end == -1:
            continue
        if "discriminator=" in content[match.start() : paren_end + 1]:
            print(
                f"  WARNING: {path}:{field_name} — primitive in "
                f"discriminated union ({type_str})",
                file=sys.stderr,
            )
            warnings += 1
    return warnings


WARNINGS = [
    warn_primitive_discriminators,
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    warnings = 0
    for models_file in sorted(PKG_DIR.glob("*/models.py")):
        content = models_file.read_text()

        for fix in FIXES:
            content, changed = fix(content)
            if changed:
                models_file.write_text(content)
                print(f"  Fixed ({fix.__name__}): {models_file}")

        for warn in WARNINGS:
            warnings += warn(content, models_file)

    if warnings:
        print(
            f"\n  {warnings} warning(s): new issues detected that may need fixes.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

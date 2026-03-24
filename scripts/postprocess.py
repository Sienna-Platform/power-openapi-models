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


FIXES = [
    fix_thermal_generation_cost_start_up,
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
        if _has_primitive_in_union(type_str) and "discriminator=" in content[match.start():]:
            # Check that the discriminator belongs to this Field() call
            field_start = match.start()
            paren_end = content.find(")", field_start)
            field_text = content[field_start : paren_end + 1] if paren_end != -1 else ""
            if "discriminator=" in field_text:
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

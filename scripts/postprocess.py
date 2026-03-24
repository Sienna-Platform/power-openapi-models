#!/usr/bin/env python3
"""Post-process generated models to fix known datamodel-codegen issues.

Currently fixes:
- Removes discriminator= from union fields where one variant is a primitive
  type (float, int, str, bool), since Pydantic requires all discriminated
  union variants to be BaseModel subclasses.
"""

import ast
import re
from pathlib import Path

PKG_DIR = Path(__file__).parent.parent / "src" / "power_openapi_models"

PRIMITIVES = {"float", "int", "str", "bool"}


def has_primitive_in_union(type_str: str) -> bool:
    """Check if a type annotation string contains a bare primitive in a union."""
    # Split on | and check each part
    parts = [p.strip() for p in type_str.split("|")]
    return any(p in PRIMITIVES for p in parts)


def fix_primitive_discriminators(content: str) -> str:
    """Remove discriminator from Field() when the union includes a primitive type."""
    lines = content.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for field definitions with type annotations containing primitives
        # Pattern: "    field_name: float | SomeModel = Field("
        field_match = re.match(r"^(\s+\w+:\s*)(.+?)\s*=\s*Field\(", line)
        if field_match and has_primitive_in_union(field_match.group(2)):
            # Collect the full Field() call (may span multiple lines)
            field_lines = [line]
            paren_depth = line.count("(") - line.count(")")
            while paren_depth > 0 and i + 1 < len(lines):
                i += 1
                field_lines.append(lines[i])
                paren_depth += lines[i].count("(") - lines[i].count(")")

            # Join and remove discriminator=
            field_text = "\n".join(field_lines)
            field_text = re.sub(
                r',\s*discriminator=["\'][^"\']+["\']',
                "",
                field_text,
            )
            result.append(field_text)
        else:
            result.append(line)
        i += 1

    return "\n".join(result)


def main() -> None:
    for models_file in PKG_DIR.glob("*/models.py"):
        content = models_file.read_text()
        fixed = fix_primitive_discriminators(content)
        if fixed != content:
            models_file.write_text(fixed)
            print(f"Fixed: {models_file}")


if __name__ == "__main__":
    main()

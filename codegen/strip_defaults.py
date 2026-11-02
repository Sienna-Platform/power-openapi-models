#!/usr/bin/env python3
"""Copy a SiennaSchemas tree without the schema `default` keyword.

The SDK contract: a schema `default` documents the value a consumer assumes for an
absent field; no SDK inserts it. A field the producer did not write stays absent, as in
the Julia package, and a schema-required field stays required even with a default. Every
generator reads this copy, so none of them (datamodel-codegen, orval, openapi-to-rust)
can fill a default.

A `default` next to a `const` stays: the schema fixes that value (a discriminator such as
`time_series_type` or `cost_type`), so it is not invented.

    python3 codegen/strip_defaults.py SCHEMA_DIR OUT_DIR
"""

import json
import shutil
import sys
from pathlib import Path

# Keys of these maps are names (a property may be called `default`), not keywords.
NAME_MAPS = {
    "properties",
    "patternProperties",
    "$defs",
    "definitions",
    "dependentSchemas",
    "schemas",
}
# Values of these keywords are data, not schemas.
DATA = {"enum", "const", "default", "examples", "example"}


def strip(node):
    if isinstance(node, list):
        return [strip(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key == "default" and "const" not in node:
            continue
        if key in DATA or key.startswith("x-"):
            out[key] = value
        elif key in NAME_MAPS and isinstance(value, dict):
            out[key] = {name: strip(schema) for name, schema in value.items()}
        else:
            out[key] = strip(value)
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git"))
    for path in target.rglob("*.json"):
        path.write_text(json.dumps(strip(json.loads(path.read_text())), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

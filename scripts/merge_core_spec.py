#!/usr/bin/env python3
"""Merge openapi-core.json and openapi-infrastructure-core.json for Python's core generation.

SiennaSchemas splits the domain-neutral association/value types (SupplementalAttribute-
Association, ComplexNumber, MinMax, UpDown, FromTo, InOut, UnitSystem, ...) into a separate
`infrastructure-core` selector. The Julia side (PowerOpenAPIModels.jl/Makefile) generates
`infrastructure-core` on its own and folds the resulting per-type files into
PowerCoreOpenAPIModels afterward (reorganize.jl) -- a file-copy merge that works because
openapi-generator emits one file per type. datamodel-codegen instead emits one `models.py`
per *input spec*, so there is no per-type file to copy after the fact: the merge has to
happen at the spec level, before codegen runs, by combining both selectors'
`components.schemas` maps into one spec and generating `core/models.py` from that in a
single pass.

Usage:
    python3 scripts/merge_core_spec.py <schema_dir> <output_path>

A name present in both selectors' schemas (e.g. `UnitSystem`, both already `$ref`s to the
same `Core/common.json` definition) is fine as long as the two definitions are identical;
if they ever differ, that is a SiennaSchemas-side collision and this fails loudly rather
than silently picking a side.

Every schema value in both selectors is a `$ref` into a file elsewhere under `schema_dir`
(e.g. `Core/common.json#/$defs/MinMax`), which a resolver follows relative to the
*referring document's own directory*. SiennaSchemas is read-only, so the merged spec is
written outside it (see the Makefile) -- these refs are rewritten to absolute paths first
so they keep resolving regardless of where the merged file ends up.
"""

import json
import sys
from pathlib import Path


def _rewrite_external_refs(node, schema_dir: Path):
    """Rewrite every non-local `$ref` (one that does not start with `#`) to an absolute path."""
    if isinstance(node, dict):
        out = {
            key: _rewrite_external_refs(value, schema_dir)
            for key, value in node.items()
        }
        ref = out.get("$ref")
        if isinstance(ref, str) and not ref.startswith("#"):
            file_part, sep, fragment = ref.partition("#")
            abs_path = (schema_dir / file_part).resolve()
            out["$ref"] = f"{abs_path}#{fragment}" if sep else str(abs_path)
        return out
    if isinstance(node, list):
        return [_rewrite_external_refs(item, schema_dir) for item in node]
    return node


def merge_schemas(core: dict, infra: dict) -> dict:
    """Union `core` and `infra`'s `components.schemas`, erroring on a genuine name collision."""
    merged = dict(core["components"]["schemas"])
    conflicts = []
    for name, schema in infra["components"]["schemas"].items():
        if name in merged and merged[name] != schema:
            conflicts.append(name)
            continue
        merged[name] = schema
    if conflicts:
        raise SystemExit(
            "openapi-core.json and openapi-infrastructure-core.json define "
            f"{sorted(conflicts)} differently -- refusing to guess which one wins. "
            "This is a SiennaSchemas-side collision, not something to paper over here."
        )
    return merged


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <schema_dir> <output_path>", file=sys.stderr)
        return 2

    schema_dir = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2])

    core = json.loads((schema_dir / "openapi-core.json").read_text())
    infra = json.loads((schema_dir / "openapi-infrastructure-core.json").read_text())

    merged_schemas = merge_schemas(core, infra)
    merged_spec = {
        "openapi": core["openapi"],
        "info": core["info"],
        "paths": {**infra.get("paths", {}), **core.get("paths", {})},
        "components": {"schemas": merged_schemas},
    }
    merged_spec = _rewrite_external_refs(merged_spec, schema_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged_spec, indent=2, sort_keys=True) + "\n")

    print(
        f"merged {len(core['components']['schemas'])} core + "
        f"{len(infra['components']['schemas'])} infrastructure-core schemas "
        f"({len(merged_schemas)} unique) -> {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

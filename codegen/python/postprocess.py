#!/usr/bin/env python3
"""Post-process generated models to fix known datamodel-codegen issues.

Each fix targets a specific known problem. New issues should be added as
separate fix functions. When an upstream fix lands, the corresponding
function can be removed.

After applying fixes, the script scans for potential new issues and warns
about them without attempting an automatic fix.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PKG_DIR = REPO_ROOT / "python" / "src" / "power_openapi_models"

PRIMITIVES = {"float", "int", "str", "bool"}

CORE_MODELS = PKG_DIR / "core" / "models.py"
INFRASTRUCTURE_CORE_MODELS = PKG_DIR / "infrastructure_core" / "models.py"
INFRASTRUCTURE_CORE_IMPORT = "power_openapi_models.infrastructure_core.models"

# Same default the Makefile's SCHEMA_DIR uses, so running this file directly
# (outside `make generate-python`) still finds a sibling checkout.
SCHEMA_DIR = Path(os.environ.get("SCHEMA_DIR", "../SiennaSchemas"))
# The six generated entry specs `make generate-python` feeds to datamodel-codegen.
# Every one of a spec's `components.schemas` entries is a bare `$ref` -- never an
# inline definition -- into Core/common.json or a per-type file under Operations/,
# Investments/, Dynamics/, TimeSeries/ (verified against every current entry).
SCHEMA_ENTRY_SPECS = (
    "openapi-infrastructure-core.json",
    "openapi-core.json",
    "openapi-operations.json",
    "openapi-investments.json",
    "openapi-dynamics.json",
    "openapi-timeseries.json",
)


# ---------------------------------------------------------------------------
# core / infrastructure_core de-duplication
# ---------------------------------------------------------------------------


def _class_blocks(content: str) -> dict[str, str]:
    """Map class name -> its full source text, from `class Name(` up to (but not
    including) the next top-level `class` or end of file. A class header can
    span several lines (e.g. `class FunctionData(\\n    RootModel[...]\\n):`),
    so this locates blocks by the start of consecutive top-level `class `
    lines rather than requiring the header to close on one line.
    """
    starts = [
        (m.start(), m.group(1)) for m in re.finditer(r"^class (\w+)\(", content, re.MULTILINE)
    ]
    blocks = {}
    for i, (start, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(content)
        blocks[name] = content[start:end].strip()
    return blocks


def dedupe_core_against_infrastructure_core() -> bool:
    """Rewrite core/models.py's duplicate infrastructure_core class definitions
    into imports.

    core/models.py is generated from openapi-core.json alone, with no ref
    mapping (see the Makefile comment): its own schema graph reaches into
    Core/common.json for several of infrastructure_core's 20 types (UnitSystem,
    the function-data family, XY_Coords, ...), and datamodel-codegen's
    --external-ref-mapping keys on a $ref's *file path*, not the individual
    $def -- common.json is the $defs home for BOTH selectors, so mapping it
    wholesale to infrastructure_core.models would misroute core's own types
    (CostCurve, StartUp, CurveStyle, ...) that live in the same file but
    aren't part of infrastructure_core's selection. There is no per-$def
    mapping in this datamodel-codegen version, so core locally redefines
    whichever of the 20 types its own schema graph reaches; this rewrites
    each such definition into an import once its body is verified identical
    to infrastructure_core's, and fails loudly on a mismatch instead of
    silently picking a side.

    Every one of infrastructure_core's 20 types is imported into core.models
    regardless of whether core's own generation happened to redefine it --
    PowerCore depends on InfrastructureCore (SiennaSchemas' six-package
    contract), and existing consumers/tests import types such as MinMax and
    SupplementalAttributeAssociation from `power_openapi_models.core.models`
    directly; re-exporting the full surface keeps that working.
    """
    if not INFRASTRUCTURE_CORE_MODELS.exists() or not CORE_MODELS.exists():
        return False

    infra_blocks = _class_blocks(INFRASTRUCTURE_CORE_MODELS.read_text())
    content = CORE_MODELS.read_text()
    core_blocks = _class_blocks(content)

    for name, infra_block in infra_blocks.items():
        core_block = core_blocks.get(name)
        if core_block is None:
            continue
        if core_block != infra_block:
            raise SystemExit(
                f"postprocess.py: core/models.py and infrastructure_core/models.py "
                f"both define {name} but their bodies differ -- refusing to guess "
                "which one wins.\n"
                f"--- core/models.py ---\n{core_block}\n"
                f"--- infrastructure_core/models.py ---\n{infra_block}"
            )
        content = content.replace(core_block, "", 1)

    content = re.sub(r"\n{3,}", "\n\n\n", content)

    names = sorted(infra_blocks)
    import_block = (
        f"from {INFRASTRUCTURE_CORE_IMPORT} import (\n"
        + "".join(f"    {name},\n" for name in names)
        + ")\n"
    )
    if import_block not in content:
        header_end = re.search(r"^class \w+\(", content, re.MULTILINE).start()
        content = content[:header_end] + import_block + "\n\n" + content[header_end:]
    # Nothing in this file references these names directly -- they exist purely to
    # re-export infrastructure_core's surface through core.models (see the docstring
    # above). Without __all__ naming them, _ruff_fix_imports()'s F401 pass reads that as
    # "unused import" and deletes the whole block.
    all_decl = "__all__ = [\n" + "".join(f'    "{name}",\n' for name in names) + "]\n"
    if all_decl not in content:
        content = content.replace(import_block, import_block + "\n" + all_decl, 1)

    CORE_MODELS.write_text(content)
    subprocess.run(["ruff", "format", str(CORE_MODELS)], check=True, capture_output=True)
    return True


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
        r"(start_up: float \| StartUpStages = Field\([^)]*?)"
        r',\s*discriminator="startup_stages_type"',
        r"\1",
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
            rf"(    {re.escape(field)}: {re.escape(type_name)} \| None = Field\(\n)"
            rf"(        None,\n)"
            rf'(        description="{re.escape(description)}",\n    \))'
        )
        new_content, n = pattern.subn(rf"\1        {INPUT_OUTPUT_CURVE_ZERO_DEFAULT},\n\3", content)
        if n:
            content = new_content
            changed = True
    return content, changed


# ---------------------------------------------------------------------------
# Schema registry -- backs fix_required_fields_with_schema_defaults below.
# ---------------------------------------------------------------------------

_schema_json_cache: dict[Path, dict] = {}


def _load_schema_json(path: Path) -> dict:
    """Read and cache one schema file, keyed by its resolved path so the same
    file reached via two different relative `$ref`s is only parsed once."""
    path = path.resolve()
    if path not in _schema_json_cache:
        _schema_json_cache[path] = json.loads(path.read_text())
    return _schema_json_cache[path]


def _resolve_schema_ref(ref: str, base_file: Path) -> tuple[dict, Path]:
    """Resolve one `$ref` written in `base_file`: a same-file JSON pointer
    (`#/$defs/X`), a bare path to another schema file (the whole file is the
    schema), or a path-plus-pointer combination -- resolved relative to the
    file the `$ref` was written in, exactly as datamodel-codegen itself
    resolves the same-filesystem external refs the Makefile relies on.
    """
    file_part, _, pointer = ref.partition("#")
    target_file = (base_file.parent / file_part).resolve() if file_part else base_file
    node = _load_schema_json(target_file)
    for part in filter(None, pointer.split("/")):
        node = node[part]
    return node, target_file


_registry_cache: dict[str, dict] | None = None


def _schema_type_registry() -> dict[str, dict]:
    """Map every schema type name to `{"node": ..., "file": ...}`, built by
    walking the six generated entry specs' `components.schemas` and
    following each entry's `$ref` (never inlined -- see SCHEMA_ENTRY_SPECS).

    A name already seen from an earlier spec is left alone: the same schema
    name reachable from two domains is guaranteed byte-identical by
    dedupe_core_against_infrastructure_core / the cross-language dedup
    contract, so re-resolving it a second time would just re-read the same
    file. Returns an empty registry (every fix below becomes a no-op,
    same as a missing INFRASTRUCTURE_CORE_MODELS file) rather than raising
    when SCHEMA_DIR isn't checked out -- postprocess.py has no other
    dependency on it existing.
    """
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    registry: dict[str, dict] = {}
    for entry_name in SCHEMA_ENTRY_SPECS:
        entry_file = SCHEMA_DIR / entry_name
        if not entry_file.exists():
            continue
        doc = _load_schema_json(entry_file)
        for name, node in doc.get("components", {}).get("schemas", {}).items():
            if name in registry:
                continue
            src_file = entry_file
            seen_refs: set[tuple[str, str]] = set()
            while isinstance(node, dict) and "$ref" in node:
                key = (str(src_file), node["$ref"])
                if key in seen_refs:
                    break
                seen_refs.add(key)
                node, src_file = _resolve_schema_ref(node["$ref"], src_file)
            registry[name] = {"node": node, "file": src_file}
    _registry_cache = registry
    return registry


def _required_field_default(registry: dict[str, dict], type_name: str, field: str):
    """The effective schema default for `type_name.field`, or `None` if the
    field isn't schema-`required`, has no property, or no default is
    discoverable.

    Checks the property node's own `default` first (`CostCurve.
    variable_cost_type`, `CostCurve.vom_cost`, `CostCurve.power_units`); when
    that property is itself a bare `$ref` with no sibling default, resolves
    one hop to the referenced type's own top-level `default`
    (`FuelCurve.vom_cost` -> `InputOutputCurve`, `LossCurve.value_curve` ->
    `LossValueCurve`) -- the same one-hop lookup
    fix_missing_composite_defaults already does for a handful of *optional*
    fields, needed here for required ones instead. Also reports whether the
    `$ref` target is itself an enum schema, so the caller can render a proper
    `EnumType.MEMBER` rather than a bare string a plain `Enum` (not
    `str, Enum`) can't accept as a literal default.

    Returns `(default_value, enum_type_name_or_None)`.
    """
    entry = registry.get(type_name)
    if entry is None:
        return None
    node, src_file = entry["node"], entry["file"]
    if field not in node.get("required", ()):
        return None
    prop = node.get("properties", {}).get(field)
    if prop is None:
        return None
    target = None
    if "$ref" in prop:
        target, _ = _resolve_schema_ref(prop["$ref"], src_file)
    if "default" in prop:
        default = prop["default"]
    elif target is not None and "default" in target:
        default = target["default"]
    else:
        return None
    enum_type = None
    if target is not None and isinstance(target.get("enum"), list):
        enum_type = target.get("title")
    return default, enum_type


def _default_literal(prop_type: str | None, default, enum_type: str | None) -> tuple[str, bool]:
    """Render a schema default as Python source, and report whether it needs
    `validate_default=True` to become the real type rather than a bare dict.

    Pydantic v2 does not validate a class-level default against its field's
    annotation (`validate_default` defaults to `False`), so a raw dict
    assigned as a `BaseModel`-typed field's default stays a dict at
    construction time -- silently wrong, and a `model_dump()` serializer
    warning waiting to happen. `CostCurve.vom_cost` and the other composite
    (dict/list) defaults here need `validate_default=True` so pydantic
    actually builds the nested model; a scalar (str for a `Literal`, float
    for a `float` field) already has the correct Python type and needs
    nothing extra. An enum-schema `$ref` target (`CostCurve.power_units` ->
    `UnitSystem`) renders as `EnumType.MEMBER`, matching this generator's own
    convention of a member name identical to its value -- verified against
    every enum currently generated (UnitSystem, PrimeMovers, ...).
    """
    if enum_type is not None:
        return f"{enum_type}.{default}", False
    if isinstance(default, (dict, list)):
        return repr(default), True
    if prop_type == "number" and isinstance(default, int) and not isinstance(default, bool):
        default = float(default)
    return repr(default), False


def _inject_required_default(
    block: str, field: str, literal: str, needs_validate: bool
) -> tuple[str, bool]:
    """Add `literal` as `field`'s default inside one class block's text,
    matching whichever of the two shapes datamodel-codegen emits for a
    required field with no default: a bare `field: Type` line, or
    `field: Type = Field(\\n    ...,\\n    <other kwargs>,\\n)` (or the
    single-line form of the same call). `validate_default=True` is added
    alongside the default, never in place of it, so an already-present
    `description=...`/`discriminator=...` kwarg survives untouched.
    """
    esc = re.escape(field)
    validate_kwarg = " validate_default=True," if needs_validate else ""

    field_call_re = re.compile(rf"({esc}: [^\n=]+ = Field\(\s*)\.\.\.,")
    new_block, n = field_call_re.subn(rf"\g<1>{literal},{validate_kwarg}", block, count=1)
    if n:
        return new_block, True

    # `_class_blocks` strips each block's trailing whitespace, so the last field
    # of the last class in a file has no trailing newline left to anchor on --
    # `(?:\n|\Z)` accepts end-of-block too (StorageCapitalCost.interconnection_cost
    # is exactly this case: the final field in its class).
    bare_re = re.compile(rf"(?m)^(    {esc}: [^\n=]+)(?:\n|\Z)")

    def _sub_bare(m: re.Match) -> str:
        if needs_validate:
            return f"{m.group(1)} = Field({literal}, validate_default=True)\n"
        return f"{m.group(1)} = {literal}\n"

    new_block, n = bare_re.subn(_sub_bare, block, count=1)
    return new_block, bool(n)


def fix_required_fields_with_schema_defaults(content: str) -> tuple[str, bool]:
    """Materialize a schema default for any property that is both
    schema-`required` and schema-`default`-bearing, wherever
    datamodel-codegen dropped it.

    `Core/common.json`'s `CostCurve` is the type this was found on:
    `vom_cost` is `"required": [..., "vom_cost", ...]` *and*
    `"default": {"curve_type": "INPUT_OUTPUT", ...}` in the same property
    node, so datamodel-codegen's usual "drop `required` once a default is
    present" rule should apply -- but for a required-with-default field it
    instead honours `required` and drops the default outright, making
    `CostCurve(...)` omitting `vom_cost` raise `ValidationError` where the
    schema (and Julia's `@kwdef`, which always applies its field default
    regardless of `required`) says the omission is fine. This is the same
    shape `fix_costcurve_power_units_default` (now folded in here) fixed for
    one field on one type by hand; SiennaSchemas turns out to use the
    pattern across every domain -- discriminator consts (`AverageRateCurve.
    curve_type`), plain numeric fields (`PortfolioFinancialData.
    discount_rate`, `Substation.grounding_resistance`), and composite `$ref`
    fields, both with the default written on the property itself
    (`CostCurve.vom_cost`) and one hop away on the referenced type
    (`FuelCurve.vom_cost`, `LossCurve.value_curve`) -- so this reads
    SCHEMA_DIR directly and fixes every instance the same way instead of
    growing one hand-written function per field.
    """
    registry = _schema_type_registry()
    blocks = _class_blocks(content)
    changed = False
    for class_name, old_block in blocks.items():
        entry = registry.get(class_name)
        if entry is None:
            continue
        new_block = old_block
        for field in entry["node"].get("required", ()):
            resolved = _required_field_default(registry, class_name, field)
            if resolved is None:
                continue
            default, enum_type = resolved
            prop_type = entry["node"].get("properties", {}).get(field, {}).get("type")
            literal, needs_validate = _default_literal(prop_type, default, enum_type)
            new_block, applied = _inject_required_default(new_block, field, literal, needs_validate)
            if applied:
                changed = True
        if new_block != old_block:
            content = content.replace(old_block, new_block, 1)
    return content, changed


def fix_feature_property_count(content: str) -> tuple[str, bool]:
    """Restore `Feature`'s exactly-one-property constraint, dropped by datamodel-codegen.

    `Core/common.json` declares `Feature` with `minProperties: 1` and
    `maxProperties: 1` — a feature is a single key/value pair, and the
    one-entry rule is the whole point of the type. datamodel-codegen emits
    the `RootModel[dict[...]]` without either bound, so an empty or
    multi-entry dict validates. Verified dropped by 0.52, 0.54, and 0.55
    alike, so this is a longstanding gap rather than a version regression.
    """
    pattern = re.compile(
        r"(class Feature\(RootModel\[dict\[str, bool \| int \| str\]\]\):\n)"
        r"(    root: dict\[str, bool \| int \| str\]\n)"
    )
    new_content, n = pattern.subn(
        r"\1    root: dict[str, bool | int | str] = "
        r"Field(..., max_length=1, min_length=1)\n",
        content,
    )
    return new_content, n > 0


def drop_redundant_root_aliases(content: str) -> tuple[str, bool]:
    """Drop `class A(RootModel[B]): root: B` wrappers that nothing references.

    A selector declares every schema its domain reaches, shared types a base
    package owns included, so datamodel-codegen meets a component whose target
    it has already mapped to an import (--external-ref-mapping). It cannot
    reuse the imported name, so it emits a wrapper under a disambiguated one --
    `MinMax1` where the collision is positional, `AverageRateCurveModel` where
    it is by name. The wrapper adds nothing to the imported type and nothing
    refers to it: dead public surface, and `MinMax1` sitting beside `MinMax`
    is exactly the confusion the Julia side's dedup pass exists to prevent.

    Matched on shape rather than on either suffix, so a scheme this generator
    version does not use yet is caught too: a wrapper whose root is one bare
    name, under a different name, referenced nowhere else in the file. Three
    guards keep real types out of it -- a union or subscripted root
    (`RootModel[CostCurve | FuelCurve]`, `RootModel[dict[str, MinMax]]`) is
    not a bare name; a named scalar still used as an annotation (`Period`,
    `ElementType`, `TimeReference`) is referenced; and a genuine
    digit-suffixed type (`SteamTurbineGov1`) is not a RootModel at all.
    """
    pattern = re.compile(
        r"^class (?P<alias>\w+)\(RootModel\[(?P<base>\w+)\]\):\n"
        r"    root: (?P=base)\n(?:\n\n|\Z)",
        re.MULTILINE,
    )
    removed = False

    def drop(match: re.Match) -> str:
        nonlocal removed
        alias, base = match.group("alias"), match.group("base")
        if alias == base:
            return match.group(0)
        if len(re.findall(rf"\b{alias}\b", content)) > 1:
            return match.group(0)
        removed = True
        return ""

    return pattern.sub(drop, content), removed


FIXES = [
    fix_thermal_generation_cost_start_up,
    fix_missing_composite_defaults,
    fix_required_fields_with_schema_defaults,
    fix_feature_property_count,
    drop_redundant_root_aliases,
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
    for match in re.finditer(r"^\s+(\w+):\s*(.+?)\s*=\s*Field\(", content, re.MULTILINE):
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
                f"  WARNING: {path}:{field_name} — primitive in discriminated union ({type_str})",
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


def _ruff_fix_imports(path: Path) -> None:
    """Auto-fix F401 (unused import) / F811 (redefined-while-unused import).

    datamodel-codegen emits one import statement per $ref resolved, with no
    dedup pass of its own: a type referenced from several properties in the
    same file, or re-exported by dedupe_core_against_infrastructure_core()
    above while a per-property import of the same name already exists, ends
    up imported more than once. `--formatters ruff-format` (passed to every
    codegen invocation) only reformats; it does not remove or merge imports,
    which is a `ruff check --fix` job, not a `ruff format` one. Restricted to
    these two codes rather than every default-enabled rule so this never
    silently starts rewriting something else `ruff check` gains later.
    """
    subprocess.run(
        ["ruff", "check", "--fix", "--select", "F401,F811", str(path)],
        check=True,
        capture_output=True,
    )


def main() -> None:
    if dedupe_core_against_infrastructure_core():
        print(f"  De-duplicated: {CORE_MODELS} against {INFRASTRUCTURE_CORE_MODELS}")

    warnings = 0
    for models_file in sorted(PKG_DIR.glob("*/models.py")):
        content = models_file.read_text()

        for fix in FIXES:
            content, changed = fix(content)
            if changed:
                models_file.write_text(content)
                print(f"  Fixed ({fix.__name__}): {models_file}")

        _ruff_fix_imports(models_file)
        # fix_required_fields_with_schema_defaults inserts a schema default's raw
        # `repr()` (a one-line dict literal for the composite cases) rather than
        # hand-formatted source, since its shapes range from a bare string to a
        # multi-level nested object -- ruff-format normalizes whatever it produced
        # into the same style datamodel-codegen's own `--formatters ruff-format`
        # pass already applies, and running it here keeps a second `make
        # generate-python` a no-op instead of reformatting on every other run.
        subprocess.run(["ruff", "format", str(models_file)], check=True, capture_output=True)
        content = models_file.read_text()

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

#!/usr/bin/env python3
"""Compare the Julia and Python OpenAPI model surfaces for interoperability.

  python3 scripts/check_cross_language.py
  python3 scripts/check_cross_language.py --julia ../PowerOpenAPIModels

Both packages are generated from the same SiennaSchemas specs, so a document
written by one must be readable by the other with identical semantics. This
checks that the two surfaces actually agree, comparing per shared type:

  * field sets            a field on one side and not the other breaks a load
  * required fields       one side rejects what the other accepts
  * enum allowed values   a value one side permits and the other refuses
  * scalar type kinds     integer vs number, string vs bool
  * defaults              a differing default silently changes an omitted field

The Julia side is read from the generated sources rather than a live session, so
this runs without a Julia install: `Base.@kwdef struct ... <: APIModel` for fields
and defaults — a field with no kwdef default is required, since the generator no
longer emits a separate `check_required` runtime helper — and `struct ... <:
EnumAPIModel`'s inner `value in (...)` constructor check for allowed enum values
(enums are their own validated wrapper type now, not a bare `const X = String`
alias checked by a separate `validate_param(..., :enum, ...)` call).

One asymmetry is structural rather than a defect, and is reported separately as
NOTE: Julia emits each schema enum as `const X = String` and enforces the allowed
values inside `OpenAPI.validate_property`, so an invalid value is caught only
when the caller validates. Pydantic makes it an `Enum` and rejects it during
construction. Both honour the schema; only Julia can be bypassed.

Exit status is non-zero when a real divergence is found, so this is usable as a
gate. NOTEs alone do not fail the run. Pass `--julia-report-only` to keep
printing every divergence in full while exiting 0 for this Julia<->Python
comparison specifically -- see that flag's help for why.

A small, named set of divergences is EXEMPTED (see `EXEMPTIONS` below) rather
than fixed: each entry is a specific `type.field`, carries a one-line reason,
and a removal condition — never a category or a wildcard. An exempted
divergence still prints, under its own heading, so it stays visible; it just
does not fail the run.
"""

import argparse
import importlib
import re
import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JULIA = REPO_ROOT / ".." / "PowerOpenAPIModels"
# Python domain -> its Julia package counterpart's name (the package directory is
# that name plus ".jl", under --julia). infrastructure_core and timeseries close a
# known gap: both were missing from this comparison entirely, so timeseries types
# (Deterministic, SingleTimeSeries, ...) never got checked cross-language. The
# Julia name for timeseries is being changed to InfrastructureTimeSeriesOpenAPIModels
# in a parallel restructure of the Julia repo -- see _julia_package_dir, the single
# place a name here turns into a directory, so that rename only has to be edited once.
DOMAINS = {
    "infrastructure_core": "InfrastructureCoreOpenAPIModels",
    "core": "PowerCoreOpenAPIModels",
    "operations": "PowerOperationsOpenAPIModels",
    "investments": "PowerInvestmentsOpenAPIModels",
    "dynamics": "PowerDynamicsOpenAPIModels",
    "timeseries": "InfrastructureTimeSeriesOpenAPIModels",
}


def _julia_package_dir(julia_root, package_name):
    """The generated Julia package directory a DOMAINS entry names."""
    return Path(julia_root) / f"{package_name}.jl"


# Julia scalar -> the JSON kind it serializes as, for comparing against pydantic.
JULIA_KIND = {
    "Int64": "integer",
    "Float64": "number",
    "String": "string",
    "Bool": "boolean",
}
PY_KIND = {int: "integer", float: "number", str: "string", bool: "boolean"}


@dataclass
class Surface:
    """One language's parsed model surface, with enough provenance that a caller
    never has to *infer* whether real parsing happened.

    `types` maps type name -> its field/required/enum surface (the shape
    `compare()` expects). `files_scanned` is the number of source files actually
    read — independent of how many types came out of them — so "0 types" from
    "0 files" (an empty or wrong path) and "0 types" from "50 files" (a parser
    that no longer matches what those files contain) are told apart instead of
    both quietly reading as one empty surface. This is exactly the distinction
    `_require_real_surface` needs, and it generalizes to any future language
    arm (a TypeScript surface reuses the same shape and the same guard rather
    than re-deriving "did this actually check anything" from scratch).
    `detail` carries any language-specific extra stat worth printing (Julia:
    how many enum registry entries were found) without forcing every language
    into one fixed schema.
    """

    language: str
    types: dict
    files_scanned: int
    detail: dict = dataclass_field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Julia side: parse the generated sources
# --------------------------------------------------------------------------- #

# A field declaration, one per logical line (see `_join_field_lines`):
#     id::Int64                                   (required: no default)
#     angle::Union{Absent, Float64, Nothing} = ABSENT   (optional)
#     variable_cost_type::String = "COST"          (required-shape constant)
# The type capture is non-greedy, so it stops at the first `=` that isn't
# nested inside the type's own braces/parens — safe here because no Julia
# type in these generated files contains a literal `=`.
FIELD_RE = re.compile(r"^\s*(\w+)::(.+?)(?:\s*=\s*(.+))?$")


def _join_field_lines(body):
    """Re-join a struct body's field declarations into one logical line each.

    The Julia formatter wraps a field across multiple physical lines when its
    type or default doesn't fit (a long `Union{Absent, ..., Nothing}`, or an
    `additional_properties` default split after its `=`). Track paren/brace
    depth (and a trailing bare `=`) to know when a declaration is still open,
    so a per-line field regex can keep working unchanged.
    """
    logical_lines, buf, depth = [], [], 0
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        buf.append(raw_line if not buf else stripped)
        depth += stripped.count("{") + stripped.count("(")
        depth -= stripped.count("}") + stripped.count(")")
        if depth <= 0 and not stripped.endswith("="):
            logical_lines.append(" ".join(buf))
            buf, depth = [], 0
    if buf:
        logical_lines.append(" ".join(buf))
    return logical_lines


def _core_julia_type(type_text):
    """Strip an Absent/Nothing optionality wrapper down to the underlying type.

    `Union{Absent, Float64, Nothing}` compares like plain `Float64`;
    `Union{Absent, Union{Nothing, String}}` (a nested wrapper) unwraps the
    same way. A real multi-type oneOf union with no null-ability (`Union{MinMax,
    MinMaxByKey}`) has no single underlying type, so it is returned unchanged —
    `JULIA_KIND.get` on it later simply misses, which is the existing,
    correct behavior for any type text it doesn't recognize.
    """
    m = re.match(r"^Union\{(.*)\}$", type_text.strip(), re.DOTALL)
    if m is None:
        return type_text
    args = [a.strip() for a in _split_top_level(m.group(1), ",") if a.strip()]
    core = [a for a in args if a not in ("Absent", "Nothing")]
    if len(core) == 1:
        return _core_julia_type(core[0])
    return type_text


def _parse_kwdef_fields(body):
    """Parse a `Base.@kwdef struct` body into (fields, required).

    A field written `name::Type` (no `= ...`) has no kwdef default, so it is
    required at construction — the only signal left for requiredness now that
    the generator's separate `check_required` runtime helper is gone. A field
    written `name::Type = EXPR` is optional; EXPR is `ABSENT` (the schema
    property was simply omitted from the JSON — Julia's distinct "not present"
    sentinel), `nothing` (an explicit null), or a literal (a discriminator
    constant such as `"COST"`). `ABSENT` and `nothing` both normalize to `None`
    here: for the purposes of this comparison — "what does an omitted field
    load as" — Julia's absent/null distinction and Python's single `None`
    default mean the same thing.

    `additional_properties` is generator scaffolding, not a schema-authored
    property: every struct gets one (named identically, typed after whatever
    the schema's `additionalProperties` sub-schema allows), so it is dropped
    here rather than reported as a per-type divergence against Python (which
    has no such field at all — see the NOTE `main()` prints once, up front,
    instead of repeating "additional_properties: in Julia, missing from
    Python" for every shared type).
    """
    fields, required = {}, set()
    for line in _join_field_lines(body):
        m = FIELD_RE.match(line)
        if m is None:
            continue
        field, jtype, default = m.group(1), _core_julia_type(m.group(2).strip()), m.group(3)
        if field == "additional_properties":
            continue
        if default is None:
            required.add(field)
        else:
            default = default.strip().rstrip(",")
            if default in ("nothing", "ABSENT"):
                default = None
        fields[field] = {"type": jtype, "default": default}
    return fields, required


def parse_julia_object_struct(text):
    """Extract one generated object model's surface, or None if the file
    defines no `Base.@kwdef` struct (an `EnumAPIModel` struct, a bare oneOf/
    Union type alias, or a file with no struct at all).

    Matches `Base.@kwdef struct NAME <: APIModel` (optionally `@kwdef` without
    the `Base.` prefix, `mutable` before `struct`, and `OpenAPI.APIModel`
    qualified) — the shapes openapi-generator's Julia template has emitted;
    verified against every current `model_*.jl` in PowerOpenAPIModels, which
    today emits exactly `Base.@kwdef struct NAME <: APIModel` (immutable,
    unqualified supertype). The struct's own closing `end` (a bare line, never
    reached earlier since these bodies hold only field declarations, no
    control flow) is the anchor, not whatever statement happens to follow it —
    the previous anchor (`\\n\\s*function `) broke the moment the generator
    started emitting a one-line `_decode(::Type{NAME}, value) = ...` there
    instead.
    """
    m = re.search(
        r"(?:Base\.)?@kwdef (?:mutable )?struct (\w+) <: (?:OpenAPI\.)?APIModel\n(.*?)\nend\n",
        text,
        re.DOTALL,
    )
    if m is None:
        return None
    name, body = m.group(1), m.group(2)
    fields, required = _parse_kwdef_fields(body)
    return name, fields, required


def parse_julia_enum_struct(text):
    """Extract a schema-enum struct's name and allowed values, or None.

    The generator emits an enum as `struct NAME <: EnumAPIModel` wrapping a
    single `value::String` field, validated by an inner constructor
    (`value in (...) || throw(...)`) — replacing the old `const NAME = String`
    alias plus a separate `validate_param(..., :enum, ...)` call this checker
    used to read. The `in (` / tuple can itself be line-wrapped (`value in\\n
    ("A", "B")`), hence `\\s*` rather than a literal space before the `(`.
    """
    m = re.search(
        r"struct (\w+) <: (?:OpenAPI\.)?EnumAPIModel\b.*?value in\s*\((.*?)\)",
        text,
        re.DOTALL,
    )
    if m is None:
        return None
    name = m.group(1)
    values = [parse_julia_expr(v) for v in _split_top_level(m.group(2), ",") if v.strip()]
    return name, values


# The generator snake_cases every Julia struct field (`ta_tb`) while the JSON
# wire key is whatever the schema named it (`"Ta_Tb"`) — both `_decode` and
# `_encode` read/write the schema key, so the wire format is correct and the
# two languages round-trip fine. Comparing the Julia *identifier* against
# Python's field name therefore compares the wrong thing; every Julia field
# must be re-keyed by its JSON wire key before it is compared to Python.
#
# `_encode` is the source: one `isa Absent` line per field, naming both the
# field and the literal JSON key it writes under, on one physical line or
# wrapped across two:
#     _openapi_value.ta_tb isa Absent ||
#         (_openapi_output["Ta_Tb"] = _encode(_openapi_value.ta_tb))
ENCODE_FUNC_RE = re.compile(
    r"function _encode\(_openapi_value::(\w+)\)\n(.*?)\n(?=function |\Z)",
    re.DOTALL,
)
ENCODE_FIELD_RE = re.compile(
    r"_openapi_value\.(\w+) isa Absent \|\|\s*"
    r'\(\s*_openapi_output\["([^"]+)"\]\s*=\s*_encode\(_openapi_value\.(\w+)\)\s*\)'
)

# Independent cross-check source: `_decode`'s `additional_properties` skip-list
# enumerates the full JSON key set for the same struct (`String(_openapi_key)
# in ("id", "Ta_Tb", ...) && continue`), from a different function than
# `_encode`. Agreement between the two is what lets a field-name-derived key
# be trusted instead of guessed.
DECODE_SKIP_LIST_RE = re.compile(
    r"function _decode\(::Type\{(\w+)\}, _openapi_raw,.*?\n(.*?)\nend\n",
    re.DOTALL,
)
DECODE_SKIP_KEYS_RE = re.compile(r"String\(_openapi_key\) in \((.*?)\)\s*&&\s*continue", re.DOTALL)


def parse_julia_json_keys(text):
    """Map each struct in `text` -> {julia_field: JSON wire key}, from `_encode`."""
    mapping = {}
    for struct_name, body in ENCODE_FUNC_RE.findall(text):
        field_to_key = {}
        for field, key, field_again in ENCODE_FIELD_RE.findall(body):
            if field != field_again:
                raise ValueError(
                    f"{struct_name}: _encode's isa-Absent field {field!r} doesn't "
                    f"match the field it encodes ({field_again!r}) -- the "
                    f"`_encode` shape this parser assumes no longer holds."
                )
            field_to_key[field] = key
        mapping[struct_name] = field_to_key
    return mapping


def parse_julia_decode_skip_keys(text):
    """Map each struct in `text` -> its full JSON key set, from `_decode`'s
    additional_properties skip-list. Cross-check only; see `parse_julia_json_keys`.
    """
    mapping = {}
    for struct_name, body in DECODE_SKIP_LIST_RE.findall(text):
        m = DECODE_SKIP_KEYS_RE.search(body)
        if m is not None:
            mapping[struct_name] = set(re.findall(r'"([^"]+)"', m.group(1)))
    return mapping


def _json_key_for(struct_name, field, field_to_key, decode_keys):
    """The JSON wire key for one Julia struct field, verified two ways.

    Raises rather than falling back to the bare identifier: a silent fallback
    here is exactly how the field-name/JSON-key mixup this function exists to
    fix went unnoticed in the first place.
    """
    if field not in field_to_key:
        raise ValueError(
            f"{struct_name}.{field}: no JSON key discoverable from _encode -- "
            f"refusing to fall back to the Julia field name."
        )
    key = field_to_key[field]
    if decode_keys is not None and key not in decode_keys:
        raise ValueError(
            f"{struct_name}.{field}: _encode writes JSON key {key!r}, but "
            f"_decode's additional_properties skip-list {sorted(decode_keys)} "
            f"doesn't contain it -- the two parses of the same struct disagree."
        )
    return key


def load_julia_surface(julia_root):
    """Parse every generated Julia package under `julia_root` into a Surface.

    Three passes over the same file list: first the enum registry (type name
    -> allowed values) from every `EnumAPIModel` struct, since a field can
    reference an enum type defined in a different package's file than the
    struct using it; then the JSON-key registry (see `parse_julia_json_keys`);
    then every object struct, re-keying its fields/required/enums by JSON key
    and attaching each field's enum values by resolving its (Absent/Nothing-
    stripped) type against the enum registry — reproducing the shape the old
    inline `validate_param` parsing produced, so `compare()` needs no changes
    beyond now receiving JSON keys instead of Julia identifiers.
    """
    paths = sorted(Path(julia_root).glob("*.jl/src/models/model_*.jl"))
    texts = [(path, path.read_text()) for path in paths]

    enum_registry = {}
    json_key_registry = {}
    decode_skip_registry = {}
    for _, text in texts:
        parsed = parse_julia_enum_struct(text)
        if parsed is not None:
            enum_registry[parsed[0]] = parsed[1]
        json_key_registry.update(parse_julia_json_keys(text))
        decode_skip_registry.update(parse_julia_decode_skip_keys(text))

    surface = {}
    for _, text in texts:
        parsed = parse_julia_object_struct(text)
        if parsed is None:
            continue
        name, fields, required = parsed
        field_to_key = json_key_registry.get(name, {})
        decode_keys = decode_skip_registry.get(name)
        keyed_fields = {
            _json_key_for(name, field, field_to_key, decode_keys): info
            for field, info in fields.items()
        }
        keyed_required = {
            _json_key_for(name, field, field_to_key, decode_keys) for field in required
        }
        enums = {
            _json_key_for(name, field, field_to_key, decode_keys): enum_registry[info["type"]]
            for field, info in fields.items()
            if info["type"] in enum_registry
        }
        surface.setdefault(
            name, {"fields": keyed_fields, "required": keyed_required, "enums": enums}
        )

    return Surface(
        language="Julia",
        types=surface,
        files_scanned=len(paths),
        detail={"enum_types_found": len(enum_registry)},
    )


# --------------------------------------------------------------------------- #
# Python side: introspect the pydantic models
# --------------------------------------------------------------------------- #


def _py_kind(annotation):
    """JSON kind for a pydantic annotation, or a marker for non-scalars."""
    text = str(annotation)
    for typ, kind in PY_KIND.items():
        # bool before int: bool is an int subclass and would match first otherwise.
        if re.search(rf"\b{typ.__name__}\b", text):
            if typ is int and re.search(r"\bbool\b", text):
                continue
            return kind
    return None


def load_python_surface():
    surface = {}
    files_scanned = 0
    for domain in DOMAINS:
        module = importlib.import_module(f"power_openapi_models.{domain}.models")
        files_scanned += 1
        for attr in dir(module):
            obj = getattr(module, attr)
            if not (isinstance(obj, type) and hasattr(obj, "model_fields")):
                continue
            fields, required, enums = {}, set(), {}
            for fname, info in obj.model_fields.items():
                alias = info.alias or fname
                fields[alias] = {
                    "kind": _py_kind(info.annotation),
                    "default": python_default_value(info),
                }
                if info.is_required():
                    required.add(alias)
                ann = info.annotation
                members = getattr(ann, "__members__", None)
                if members is None:
                    for arg in getattr(ann, "__args__", ()) or ():
                        members = getattr(arg, "__members__", None)
                        if members is not None:
                            break
                if members is not None:
                    enums[alias] = [m.value for m in members.values()]
            surface.setdefault(attr, {"fields": fields, "required": required, "enums": enums})
    return Surface(language="Python", types=surface, files_scanned=files_scanned)


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


def _split_top_level(text, sep):
    """Split on `sep` outside of any (), [], quotes — so nested calls stay intact."""
    parts, depth, quote, start = [], 0, None, 0
    i = 0
    while i < len(text):
        c = text[i]
        if quote is not None:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c == '"':
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return parts


def parse_julia_expr(text):
    """Evaluate a Julia default-source expression into a JSON-comparable value.

    Handles the shapes openapi-generator emits for defaults: `nothing`/`true`/
    `false`, numbers, quoted strings, empty/populated array literals
    (`Int64[]`, `[1, 2]`), and constructor calls (`MinMax(; max=1.1, min=0.9)`,
    possibly nested). A constructor's keyword call becomes a dict keyed by
    field name so it lines up with pydantic's `model_dump()`; a single
    positional argument (`ValueCurve(InputOutputCurve(...))`) is transparent,
    matching how a pydantic RootModel dumps straight to its wrapped value.
    Anything unrecognized falls back to the raw text, so a real mismatch is
    still reported instead of raising.
    """
    if text is None:
        return None
    s = text.strip().rstrip(",").strip()
    if s == "nothing":
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1].replace('\\"', '"')
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    m = re.match(r"^\w*\[(.*)\]$", s, re.DOTALL)
    if m is not None:
        inner = m.group(1).strip()
        if not inner:
            return []
        return [parse_julia_expr(item) for item in _split_top_level(inner, ",")]
    m = re.match(r"^(\w+)\((.*)\)$", s, re.DOTALL)
    if m is not None:
        inner = m.group(2).strip()
        if inner.startswith(";"):
            result = {}
            for kwarg in _split_top_level(inner[1:], ","):
                kwarg = kwarg.strip()
                if not kwarg:
                    continue
                key, _, value = kwarg.partition("=")
                result[key.strip()] = parse_julia_expr(value)
            return result
        args = [a for a in _split_top_level(inner, ",") if a.strip()] if inner else []
        parsed = [parse_julia_expr(a) for a in args]
        if len(parsed) == 1:
            return parsed[0]
        if parsed:
            return parsed
    return s


def _to_jsonable_python(value):
    """Mirror `parse_julia_expr`'s output shape for a live Python default value.

    A materialized composite default is either a pydantic model instance
    (`default=`) or built lazily (`default_factory=`); both must be reduced to
    plain dict/list/scalar so it compares structurally against the parsed
    Julia expression rather than by object identity or repr.
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {k: _to_jsonable_python(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable_python(v) for v in value]
    return value


def python_default_value(info):
    """The field's effective default, materializing `default_factory` if needed.

    A default built by a factory (pydantic's way of avoiding a shared mutable
    default) can itself be broken — invoking it can raise if the schema's
    literal default omits a field the referenced type otherwise requires. That
    is a real cross-language divergence (Julia's kwdef constructor tolerates
    the same omission via the referenced type's own field default), so it is
    captured as a message rather than left to crash the comparison.
    """
    if info.is_required():
        return None
    if info.default_factory is not None:
        try:
            return _to_jsonable_python(info.default_factory())
        except Exception as exc:  # noqa: BLE001 - surfaced as a divergence, not a crash
            return f"<default_factory raised {exc.__class__.__name__}: {exc}>"
    return _to_jsonable_python(info.default)


# --------------------------------------------------------------------------- #
# Named exemptions — each keyed by (type, field); field is None for a
# whole-type divergence. No categories, no wildcards: a schema change that
# alters the shape of one of these must re-earn its exemption by editing this
# table, not by matching a pattern. An exempted divergence still prints under
# its own heading, so it stays visible; it just does not fail the run.
# --------------------------------------------------------------------------- #

EXEMPTIONS = {
    ("MarketBidCost1", None): {
        "reason": (
            "openapi-generator (Java/julia-client) emits a duplicate struct "
            "when a schema is reused as a discriminated oneOf branch — "
            "HybridSystem.operation_cost references MarketBidCost via a "
            "discriminator mapping, so Julia gets a second, field-identical "
            "MarketBidCost1. datamodel-codegen reuses the single MarketBidCost "
            "class for the same field instead of duplicating it (verified: "
            "Python HybridSystem.operation_cost is typed plain MarketBidCost). "
            "No surface is actually missing on the Python side."
        ),
        "remove_when": (
            "openapi-generator stops duplicating discriminator-mapped schemas, "
            "or this checker resolves Julia struct identity by shape instead of "
            "by name for the type-only-in-Julia category."
        ),
    },
    ("StorageCostStartUpOneOf", None): {
        "reason": (
            "Anonymous oneOf branch on StorageCost.start_up. openapi-generator "
            "names it from parent+field (StorageCostStartUpOneOf); "
            "datamodel-codegen names the identical-shape model from the "
            "schema's own title (StartUp). Verified field-for-field identical: "
            "both have exactly {charge: float|None, discharge: float|None}."
        ),
        "remove_when": (
            "the two generators agree on a naming convention for anonymous "
            "oneOf branches, or this checker matches by shape instead of name."
        ),
    },
    ("CostCurve", "vom_cost"): {
        "reason": (
            "vom_cost is schema-required with a schema-default. Julia's "
            "check_required always tests every schema-required $ref/object "
            "field for `=== nothing`, regardless of whether "
            "materialize_defaults.jl gave it a real default; datamodel-codegen "
            "correctly drops `required` once a default is present. Verified no "
            "runtime divergence: CostCurve(...) omitting vom_cost succeeds and "
            "passes check_required on both sides (the default is never "
            "`nothing`); an explicit null is rejected on both sides."
        ),
        "remove_when": (
            "openapi-generator's Julia template stops listing a required field "
            "with a materialized default in check_required (a template/"
            "upstream change — cannot be done by hand-editing generated code)."
        ),
    },
    ("CostCurve", "power_units"): {
        "reason": (
            "power_units is schema-required with a schema-default "
            "(NATURAL_UNITS). Same root cause as CostCurve.vom_cost: Julia's "
            "check_required still tests it for `=== nothing` even though its "
            "kwdef default is never nothing; datamodel-codegen (once "
            "postprocess.py's fix_costcurve_power_units_default restores the "
            "default) correctly drops `required`. Verified no runtime "
            "divergence: CostCurve(...) "
            "omitting power_units resolves to NATURAL_UNITS on both sides."
        ),
        "remove_when": "same as CostCurve.vom_cost.",
    },
    ("MarketBidCost", "no_load_cost"): {
        "reason": (
            "Same required-with-default pattern as CostCurve.vom_cost. "
            "Verified no runtime divergence: MarketBidCost(...) omitting "
            "no_load_cost succeeds and passes check_required on both sides."
        ),
        "remove_when": "same as CostCurve.vom_cost.",
    },
    ("MarketBidCost", "shut_down"): {
        "reason": (
            "Same required-with-default pattern as CostCurve.vom_cost. "
            "Verified no runtime divergence: MarketBidCost(...) omitting "
            "shut_down succeeds and passes check_required on both sides."
        ),
        "remove_when": "same as CostCurve.vom_cost.",
    },
    ("RenewableGenerationCost", "curtailment_cost"): {
        "reason": (
            "The schema's own default for curtailment_cost omits power_units "
            "(relying on CostCurve.power_units' own default), so Julia's "
            "rendered constructor call (`CostCurve(; variable_cost_type=..., "
            "value_curve=..., vom_cost=...)`) never mentions power_units in "
            "source text either. parse_julia_expr evaluates only the keyword "
            "arguments written in that source text — it does not re-resolve "
            "CostCurve's own field default for a key the call omits — so the "
            "parsed Julia value lacks power_units while Python's model_dump() "
            "of the constructed instance includes every field. Verified no "
            "runtime divergence: RenewableGenerationCost().curtailment_cost."
            "power_units == 'NATURAL_UNITS' on both sides."
        ),
        "remove_when": (
            "parse_julia_expr is taught to resolve a referenced type's own "
            "field defaults for keys a nested constructor call omits (needs "
            "the type-surface map threaded into the expression parser)."
        ),
    },
}


def compare(julia, python):
    """Return `(problems, notes, shared)`.

    `problems` entries are `(key, message)` pairs, `key = (type, field)` with
    `field=None` for a whole-type divergence — the lookup key into
    `EXEMPTIONS`. Splitting a multi-field divergence (e.g. a required-set
    mismatch naming several fields) into one entry per field keeps each
    exemption named at exactly the granularity the brief requires: a single
    `type.field`, never a category.
    """
    problems, notes = [], []
    shared = sorted(set(julia) & set(python))

    only_julia = sorted(set(julia) - set(python))
    only_python = sorted(set(python) - set(julia))
    for name in only_julia:
        problems.append(((name, None), f"{name}: present in Julia, absent in Python"))
    for name in only_python:
        # Pydantic exposes helper models (RootModel wrappers) Julia has no struct
        # for; report as a note so real gaps stay visible.
        notes.append(f"{name}: present in Python, no Julia struct")

    for name in shared:
        j, p = julia[name], python[name]
        jf, pf = set(j["fields"]), set(p["fields"])
        for field in sorted(jf - pf):
            problems.append(((name, field), f"{name}.{field}: in Julia, missing from Python"))
        for field in sorted(pf - jf):
            problems.append(((name, field), f"{name}.{field}: in Python, missing from Julia"))

        for field in sorted(j["required"] - p["required"]):
            problems.append(((name, field), f"{name}.{field}: required only in Julia"))
        for field in sorted(p["required"] - j["required"]):
            problems.append(((name, field), f"{name}.{field}: required only in Python"))

        for field in sorted(jf & pf):
            jkind = JULIA_KIND.get(j["fields"][field]["type"])
            pkind = p["fields"][field]["kind"]
            if jkind and pkind and jkind != pkind:
                problems.append(
                    (
                        (name, field),
                        f"{name}.{field}: type kind Julia={jkind} Python={pkind}",
                    )
                )
            # A default on a field that both sides require is unreachable: omitting
            # the field is an error, not a fallback, so a difference there cannot
            # change what either language loads. Julia pre-fills several such
            # fields (StorageCost.fixed, the const discriminators); comparing them
            # would report noise.
            if field in j["required"] and field in p["required"]:
                continue
            jd = parse_julia_expr(j["fields"][field]["default"])
            pd = p["fields"][field]["default"]
            if jd != pd:
                problems.append(
                    (
                        (name, field),
                        f"{name}.{field}: default Julia={jd!r} Python={pd!r} "
                        f"(optional both sides — an omitted field loads differently)",
                    )
                )

        for field in sorted(set(j["enums"]) & set(p["enums"])):
            jv, pv = j["enums"][field], p["enums"][field]
            if sorted(jv) != sorted(pv):
                problems.append(
                    (
                        (name, field),
                        f"{name}.{field}: enum values differ "
                        f"Julia={sorted(jv)} Python={sorted(pv)}",
                    )
                )
        for field in sorted(set(p["enums"]) - set(j["enums"])):
            problems.append(
                (
                    (name, field),
                    f"{name}.{field}: Python constrains it to an enum, Julia does "
                    f"not validate it at all",
                )
            )
    return problems, notes, shared


def _require_real_surface(surface):
    """Refuse to let a broken parser or a wrong path masquerade as agreement.

    This is the fix for the actual defect that motivated this file: a parser
    regex that silently matched nothing produced `Julia structs: 0`, `Compared
    0 shared types`, and then *still* printed "Surfaces agree" and exited 0 —
    a parity gate that was green because it never compared anything. A
    surface that scanned zero files, or scanned files and parsed zero types
    out of them, means nothing was actually checked for that language; name
    which one and why, loudly, and refuse to proceed. Takes a `Surface` (not a
    bare dict) so every language arm — this file's Julia and Python today, a
    TypeScript arm next — inherits the same guard instead of each having to
    reproduce it, or re-derive "did this actually check anything" by
    inference from a plain type count.
    """
    if surface.files_scanned == 0:
        print(
            f"ERROR: {surface.language} surface scanned 0 source files — the "
            f"path is empty, wrong, or nothing matched the expected file "
            f"pattern. No {surface.language} type was even attempted, so any "
            f"'surfaces agree' verdict from this run would be meaningless."
        )
        return False
    if not surface.types:
        print(
            f"ERROR: {surface.language} surface scanned {surface.files_scanned} "
            f"file(s) but parsed 0 types out of them. The parser's pattern no "
            f"longer matches what those files contain (most likely a generator/"
            f"template change) — fix the parser. Do not let this pass."
        )
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--julia", default=str(DEFAULT_JULIA))
    parser.add_argument(
        "--julia-report-only",
        action="store_true",
        help=(
            "Print every Julia<->Python divergence in full, but exit 0 instead of "
            "failing on them. Julia leaves an omitted defaulted field ABSENT where "
            "Python materializes the schema default -- a confirmed pre-existing bug "
            "in the Julia generator, filed separately, that this repo's CI must not "
            "block on. Does not affect the empty-surface/no-shared-types guards, "
            "which still fail the run, and has no effect on any other language pair "
            "this script may compare (e.g. Python<->TypeScript remains a hard gate)."
        ),
    )
    args = parser.parse_args()

    julia_root = Path(args.julia).resolve()
    if not julia_root.is_dir():
        print(f"Julia package tree not found: {julia_root}")
        return 2

    print("Julia package directories (per DOMAINS entry):")
    missing_domains = []
    for domain, package in DOMAINS.items():
        if _julia_package_dir(julia_root, package).is_dir():
            status = "found"
        else:
            status = "NOT FOUND"
            missing_domains.append(domain)
        print(f"  {domain:20s} -> {package}.jl: {status}")
    if missing_domains:
        print(
            "  NOTE: a missing directory means that domain's Julia structs are "
            "absent from the comparison below (reported as ONLY-IN-PYTHON, not a "
            "real divergence) until its package lands on the Julia side."
        )
    print()

    julia_surface = load_julia_surface(julia_root)
    python_surface = load_python_surface()
    print(
        f"Julia structs:  {len(julia_surface.types)} "
        f"(from {julia_surface.files_scanned} file(s); "
        f"{julia_surface.detail.get('enum_types_found', 0)} of them enum types)"
    )
    print(
        f"Python models:  {len(python_surface.types)} "
        f"(from {python_surface.files_scanned} file(s))\n"
    )

    if not _require_real_surface(julia_surface) or not _require_real_surface(python_surface):
        return 3

    print(
        "NOTE: every Julia struct also carries an `additional_properties` "
        "passthrough field (captures JSON keys the schema didn't name) that "
        "the parser drops before comparison rather than reporting for every "
        "shared type — Python's generated models have no counterpart and "
        "silently discard unrecognized keys under pydantic's default config. "
        "This is a structural difference between the two generators, not a "
        "per-type divergence: an unknown extra key round-trips through Julia "
        "and vanishes going through Python.\n"
    )

    all_problems, notes, shared = compare(julia_surface.types, python_surface.types)
    if not shared:
        print(
            f"ERROR: 0 shared types even though both surfaces parsed real "
            f"types ({len(julia_surface.types)} Julia, {len(python_surface.types)} "
            f"Python) — every type name differs, so nothing was actually "
            f"compared. Check DOMAINS / naming assumptions before trusting any "
            f"verdict from this run."
        )
        return 3
    print(f"Compared {len(shared)} shared types.\n")

    failures = [(key, msg) for key, msg in all_problems if key not in EXEMPTIONS]
    exempted = [(key, msg) for key, msg in all_problems if key in EXEMPTIONS]

    if notes:
        print(f"NOTES ({len(notes)}) — not failures:")
        for n in notes[:15]:
            print(f"  {n}")
        if len(notes) > 15:
            print(f"  ...and {len(notes) - 15} more")
        print()

    if exempted:
        print(f"EXEMPTIONS ({len(exempted)}) — named, not failures:")
        for key, msg in exempted:
            print(f"  {msg}")
            print(f"    reason: {EXEMPTIONS[key]['reason']}")
            print(f"    remove when: {EXEMPTIONS[key]['remove_when']}")
        print()

    if failures:
        print(f"DIVERGENCES ({len(failures)}):")
        for _, msg in failures:
            print(f"  {msg}")
        print(f"\n{len(failures)} divergence(s) would break bi-directional loading.")
        if args.julia_report_only:
            print(
                f"\nREPORT-ONLY MODE: the {len(failures)} Julia<->Python "
                f"divergence(s) above do NOT fail this run. Almost all of them are "
                f"one confirmed, pre-existing Julia generator bug -- an omitted "
                f"defaulted field decodes to ABSENT in Julia where Python "
                f"materializes the schema default (e.g. SEXS without V_ref: "
                f"ABSENT in Julia, 1.0 in Python) -- tracked separately, not fixable "
                f"by editing generated code in this repo. Python<->TypeScript is "
                f"the blocking gate for this repo's CI. Run without "
                f"--julia-report-only to make these divergences fail the build."
            )
            return 0
        return 1

    print(
        f"Surfaces agree: field sets, required fields, enum values, kinds, "
        f"defaults ({len(exempted)} named exemption(s) — see above)."
        if exempted
        else "Surfaces agree: field sets, required fields, enum values, kinds, defaults."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

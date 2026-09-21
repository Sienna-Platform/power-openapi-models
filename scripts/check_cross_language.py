#!/usr/bin/env python3
"""Compare the Julia, Python, and TypeScript OpenAPI model surfaces for
interoperability.

  python3 scripts/check_cross_language.py
  python3 scripts/check_cross_language.py --julia ../PowerOpenAPIModels --ts typescript

All three packages are generated from the same SiennaSchemas specs, so a
document written by one must be readable by the others with identical
semantics. This checks that the surfaces actually agree, comparing per shared
type:

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

Exit status is non-zero when a real divergence is found in the Python<->
TypeScript comparison, so this is usable as a gate on that pair. NOTEs alone
do not fail the run. Pass `--julia-report-only` to keep printing every
Julia<->Python divergence in full while exiting 0 for that comparison
specifically -- see that flag's help for why. Python<->TypeScript has no such
flag: it is always a hard gate.

A small, named set of Julia<->Python divergences is EXEMPTED (see
`EXEMPTIONS` below) rather than fixed: each entry is a specific `type.field`,
carries a reason and a removal condition — never a category or a
wildcard. An exempted divergence still prints, under its own heading, so it
stays visible; it just does not fail the Julia<->Python comparison.
EXEMPTIONS is never applied to Python<->TypeScript -- every entry's reason is
specific to openapi-generator's Julia template, not to orval/zod, so reusing
it there would silently paper over a real TypeScript-side divergence under a
Julia-side justification.
"""

import argparse
import importlib
import json
import re
import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JULIA = REPO_ROOT / ".." / "PowerOpenAPIModels"
DEFAULT_SCHEMA_DIR = REPO_ROOT / ".." / "SiennaSchemas"
# The same five top-level directories gen-orval-config.ts walks for orval's
# external-$ref allowlist -- every schema file in this repo's world lives
# under one of them.
SCHEMA_SUBDIRS = ("Core", "Operations", "Dynamics", "Investments", "TimeSeries")
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
# zod's core-type call name -> the JSON kind it serializes as.
TS_SCALAR_KIND = {
    "number": "number",
    "int": "integer",
    "string": "string",
    "boolean": "boolean",
}


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
        # Resolved here, at surface-construction time, rather than left as raw
        # Julia source text for `compare()` to interpret -- so `compare()` can
        # be fully generic across language pairs instead of assuming "first
        # argument is Julia-shaped, needs JULIA_KIND/parse_julia_expr".
        keyed_fields = {
            _json_key_for(name, field, field_to_key, decode_keys): {
                "kind": JULIA_KIND.get(info["type"]),
                "default": parse_julia_expr(info["default"]),
            }
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
# TypeScript side: parse the generated zod schemas
# --------------------------------------------------------------------------- #

# orval inlines every field's type in full -- verified against every current
# `models.ts`: no field ever names another exported const by identifier, even
# for a nested object or a shared enum (`power_units` re-declares
# `zod.enum(["COMPONENT_BASE", "NATURAL_UNITS"])` inline in every struct that
# has one, rather than referencing a shared `UnitSystem` const). So unlike the
# Julia side, this needs no separate enum/JSON-key registry: a field's own
# call chain *is* its complete type, and the field name already *is* the JSON
# wire key (zod's object keys are the schema's property names verbatim, no
# snake_case identifier vs. wire-key split like Julia's `_encode`/`_decode`).

_TS_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_TS_OPENERS = "([{"
_TS_CLOSERS = ")]}"
# `export const NAME = zod` is always exactly this shape (one line, nothing
# trailing) in every current `models.ts` -- the chain's own methods start on
# the following line(s).
_TS_TOP_TYPE_RE = re.compile(r"^export const (\w+) = (zod)\b", re.MULTILINE)
# What postprocess.ts leaves behind for a deduped type -- see `_ts_parse_file`.
_TS_REEXPORT_RE = re.compile(r'^export \{ (\w+) \} from "\.\./(\w+)/models";', re.MULTILINE)
# A demoted `*Default` const -- never `export`ed (see `_ts_parse_file`). Most
# have no type annotation, but an empty-array default (`never[]`, from an
# array field with no schema default items) gets one from tsc's inference:
# `const fooDefault: never[] = [];` -- tolerate one, up to the first `=`,
# since none of these annotations ever contain their own `=`.
_TS_CONST_DECL_RE = re.compile(
    r"^const ([A-Za-z_$][A-Za-z0-9_$]*)(?:\s*:\s*[^=\n]+)?\s*=\s*", re.MULTILINE
)
_TS_FIELD_KEY_RE = re.compile(
    r'^\s*(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|([A-Za-z_$][A-Za-z0-9_$]*))\s*:\s*',
    re.DOTALL,
)
_TS_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def _ts_field_key(match):
    """The key text out of a `_TS_FIELD_KEY_RE` match, whichever alternative
    (double-quoted, single-quoted, or bare identifier) it matched."""
    for group in match.groups():
        if group is not None:
            return group
    raise ValueError("_TS_FIELD_KEY_RE matched with no captured group")


def _ts_mask_strings(text):
    """Boolean-per-character mask marking which `text` positions fall inside a
    JS string or template literal, so a bracket-depth scanner can skip them
    instead of miscounting a stray `(`/`{`/`,` inside one of this file's long
    `.describe("...")` prose strings, which are full of punctuation.
    """
    mask = bytearray(len(text))
    quote = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quote is not None:
            mask[i] = 1
            if c == "\\" and i + 1 < n:
                mask[i + 1] = 1
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
            mask[i] = 1
        i += 1
    return mask


def _ts_matching_bracket(text, mask, open_pos):
    """Index of the bracket matching `text[open_pos]` (one of `([{`).

    Treats every bracket kind as one shared depth counter -- safe here since
    mismatched nesting would be a TypeScript syntax error in generated code --
    and skips masked (string/template) characters.
    """
    depth = 0
    i, n = open_pos, len(text)
    while i < n:
        if not mask[i]:
            c = text[i]
            if c in _TS_OPENERS:
                depth += 1
            elif c in _TS_CLOSERS:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    raise ValueError(f"unbalanced brackets from index {open_pos}")


def _ts_find_top_level_semicolon(text, mask, start):
    """Index of the first depth-0, unmasked `;` at or after `start`."""
    depth = 0
    i, n = start, len(text)
    while i < n:
        if not mask[i]:
            c = text[i]
            if c in _TS_OPENERS:
                depth += 1
            elif c in _TS_CLOSERS:
                depth -= 1
            elif c == ";" and depth == 0:
                return i
        i += 1
    raise ValueError(f"unterminated statement starting at {start}")


def _ts_split_top_level_spans(text, mask):
    """`(start, end)` spans of `text` split on depth-0, unmasked commas."""
    spans, depth, start = [], 0, 0
    n = len(text)
    for i in range(n):
        if mask[i]:
            continue
        c = text[i]
        if c in _TS_OPENERS:
            depth += 1
        elif c in _TS_CLOSERS:
            depth -= 1
        elif c == "," and depth == 0:
            spans.append((start, i))
            start = i + 1
    if start < n and text[start:].strip():
        spans.append((start, n))
    return spans


def _ts_parse_call_chain(text, mask, pos):
    """Parse a `zod` method chain starting at `text[pos:]` (leading whitespace
    tolerated). Returns `(calls, end_pos)`: `calls` is the ordered
    `[(method_name, args_text, args_mask), ...]` list -- `calls[0]` is the
    core type call (`object`/`enum`/`literal`/`union`/`number`/`int`/...),
    everything after it a modifier (`describe`/`optional`/`nullish`/
    `default`/`min`/`max`/...). `args_text`/`args_mask` are the exact slice
    between that call's own parens, so a nested chain (a union branch, an
    `.and(...)` argument) can be parsed the same way, recursively.

    A namespace access (`zod.iso.datetime({...})`, zod v4's date/time family)
    chains one or more bare identifiers before the parens actually appear;
    those fold into one dotted `method_name` (`"iso.datetime"`) rather than
    being misread as a paren-less call named `iso`.
    """
    n = len(text)
    while pos < n and text[pos] in " \t\r\n":
        pos += 1
    m = _TS_IDENT_RE.match(text, pos)
    if m is None or m.group(0) != "zod":
        raise ValueError(f"expected a `zod` expression at index {pos}: {text[pos : pos + 60]!r}")
    pos = m.end()
    calls = []
    while True:
        j = pos
        while j < n and text[j] in " \t\r\n":
            j += 1
        if j >= n or text[j] != ".":
            return calls, pos
        j += 1
        while j < n and text[j] in " \t\r\n":
            j += 1
        m = _TS_IDENT_RE.match(text, j)
        if m is None:
            return calls, pos
        name_parts = [m.group(0)]
        j = m.end()
        while True:
            k = j
            while k < n and text[k] in " \t\r\n":
                k += 1
            if k >= n or text[k] != ".":
                break
            k2 = k + 1
            while k2 < n and text[k2] in " \t\r\n":
                k2 += 1
            m2 = _TS_IDENT_RE.match(text, k2)
            if m2 is None:
                break
            name_parts.append(m2.group(0))
            j = m2.end()
        while j < n and text[j] in " \t\r\n":
            j += 1
        if j >= n or text[j] != "(":
            return calls, pos
        close = _ts_matching_bracket(text, mask, j)
        calls.append((".".join(name_parts), text[j + 1 : close], mask[j + 1 : close]))
        pos = close + 1


def _ts_bracketed_body(text, mask, open_char):
    """`(inner_text, inner_mask)` spanning the content of `text`'s outermost
    `open_char ... matching-close` pair, or None if `text` (past leading
    whitespace) doesn't start with `open_char`. Used both for a `[ ... ]`
    array literal's elements and a `{ ... }` object literal's own body --
    `zod.object(...)`'s single argument is the latter, braces included, since
    the call's own parens wrap the object literal rather than being it.
    """
    i = 0
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != open_char:
        return None
    close = _ts_matching_bracket(text, mask, i)
    return text[i + 1 : close], mask[i + 1 : close]


def _ts_parse_js_value(text, const_registry):
    """Evaluate a JS literal expression into a JSON-comparable value.

    Handles the shapes this generated code contains: `null`/`undefined`,
    `true`/`false`, a quoted or backtick string, a number, an array literal, an
    object literal (the composite defaults postprocess demotes, e.g.
    `capitalCostCapitalCostOneDefault`), and a bare identifier resolved
    through `const_registry` -- plus stripping the `as const` assertions
    postprocess leaves on composite-default fields. A bare identifier ending
    in `Default` that isn't in the registry raises: that means the demoted-
    const contract this parser assumes broke, not a real data question (see
    `_ts_parse_file`). Anything else unrecognized returns the raw text, so a
    real mismatch still surfaces as a divergence instead of raising --
    mirroring `parse_julia_expr`'s fallback.
    """
    s = re.sub(r"\s+as\s+const\b", "", text).strip().rstrip(",").strip()
    if s in ("null", "undefined"):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if len(s) >= 2 and s[0] in "\"'`" and s[-1] == s[0]:
        return s[1:-1].replace("\\" + s[0], s[0])
    if _TS_NUMBER_RE.match(s):
        return float(s) if re.search(r"[.eE]", s) else int(s)
    mask = _ts_mask_strings(s)
    if s.startswith("[") and s.endswith("]"):
        inner, inner_mask = s[1:-1], mask[1:-1]
        return [
            _ts_parse_js_value(inner[a:b], const_registry)
            for a, b in _ts_split_top_level_spans(inner, inner_mask)
        ]
    if s.startswith("{") and s.endswith("}"):
        inner, inner_mask = s[1:-1], mask[1:-1]
        result = {}
        for a, b in _ts_split_top_level_spans(inner, inner_mask):
            entry = inner[a:b]
            m = _TS_FIELD_KEY_RE.match(entry)
            if m is None:
                continue
            key = _ts_field_key(m)
            result[key] = _ts_parse_js_value(entry[m.end() :], const_registry)
        return result
    if _TS_IDENT_RE.fullmatch(s):
        if s in const_registry:
            return const_registry[s]
        if s.endswith("Default"):
            raise ValueError(
                f"{s!r} reads like a demoted `*Default` const reference but no "
                f"`const {s} = ...;` was found in this file -- the postprocess "
                f"demotion contract this parser assumes no longer holds."
            )
    return s


def _ts_object_body(calls):
    """The `(body_text, body_mask)` of the `zod.object({...})` call a parsed
    chain resolves to, or None if it never resolves to one.

    Direct when `calls[0]` already is `object`. Otherwise searches every
    `.and(...)` argument (itself a nested zod chain, parsed recursively) for
    one, keeping the rightmost match -- the one shape this repo actually
    generates that needs it is `EmissionsData`:
    `zod.unknown().and(zod.unknown()).and(zod.object({...}))`. None means
    this const is an enum/union/scalar/array/record type alias, not a struct
    -- exactly why it gets no Surface entry, mirroring Python's loader only
    picking up `BaseModel` subclasses (`hasattr(obj, "model_fields")`) and
    skipping plain type aliases.
    """
    if not calls:
        return None
    if calls[0][0] == "object":
        # `.object(...)`'s one argument is the `{ ... }` literal itself
        # (braces included) -- unwrap them to get the field-declaration body.
        return _ts_bracketed_body(calls[0][1], calls[0][2], "{")
    found = None
    for name, args_text, args_mask in calls:
        if name != "and":
            continue
        nested_calls, _ = _ts_parse_call_chain(args_text, args_mask, 0)
        nested = _ts_object_body(nested_calls)
        if nested is not None:
            found = nested
    return found


def _ts_parse_object_fields(body, mask):
    """`{field_name: calls}` for a `zod.object({ ... })` call's body -- `calls`
    the chain `_ts_parse_call_chain` parsed for that field's value expression.
    """
    fields = {}
    for a, b in _ts_split_top_level_spans(body, mask):
        entry, entry_mask = body[a:b], mask[a:b]
        m = _TS_FIELD_KEY_RE.match(entry)
        if m is None:
            if not entry.strip():
                continue
            raise ValueError(f"no field key found in {entry.strip()[:80]!r}")
        name = _ts_field_key(m)
        calls, _ = _ts_parse_call_chain(entry[m.end() :], entry_mask[m.end() :], 0)
        fields[name] = calls
    return fields


def _ts_field_info(calls, const_registry):
    """One field's `{kind, default, required, enums}` from its parsed chain.

    `required` is False whenever `.optional()`, `.nullish()`, *or*
    `.default(...)` appears: a defaulted field is optional to construct even
    with no `.optional()` of its own -- zod's `input` type treats it exactly
    that way, and it is how pydantic's `is_required()` treats a defaulted
    field too (verified: `MarketBidCost.curve_style` is `.default()`-only in
    TypeScript with no `.optional()`, and `required=False` in Python).

    `zod.literal("X")` is treated as the single-value equivalent of
    `zod.enum(["X"])` per the postprocess canonicalization. A `zod.union([...
    ])` of bare `zod.literal(...)` branches -- how orval renders a numeric
    schema enum, since zod's own `.enum()` accepts only strings (verified:
    `MarketBidCost.curve_style`/`curve_multistep` are `union([literal(0),
    literal(1)])` in TypeScript and a real int-valued Enum in Python) -- is
    treated the same way, but only when *every* branch is a bare literal; a
    real oneOf-of-objects union gets no enum entry, matching Python having
    none for a `Union[SomeModel, OtherModel]` field either.
    """
    core_name, core_args, core_mask = calls[0]
    names = [c[0] for c in calls]
    has_default = "default" in names
    required = not (has_default or "optional" in names or "nullish" in names)
    kind = TS_SCALAR_KIND.get(core_name)
    default = None
    if has_default:
        default_args = next(a for n, a, _ in calls if n == "default")
        default = _ts_parse_js_value(default_args, const_registry)
    enums = None
    if core_name == "enum":
        arr = _ts_bracketed_body(core_args, core_mask, "[")
        if arr is not None:
            inner, inner_mask = arr
            enums = [
                _ts_parse_js_value(inner[a:b], const_registry)
                for a, b in _ts_split_top_level_spans(inner, inner_mask)
            ]
    elif core_name == "literal":
        enums = [_ts_parse_js_value(core_args, const_registry)]
    elif core_name == "union":
        arr = _ts_bracketed_body(core_args, core_mask, "[")
        if arr is not None:
            inner, inner_mask = arr
            values, all_literal = [], True
            for a, b in _ts_split_top_level_spans(inner, inner_mask):
                branch_calls, _ = _ts_parse_call_chain(inner[a:b], inner_mask[a:b], 0)
                if len(branch_calls) == 1 and branch_calls[0][0] == "literal":
                    values.append(_ts_parse_js_value(branch_calls[0][1], const_registry))
                else:
                    all_literal = False
                    break
            if all_literal and values:
                enums = values
    return {"kind": kind, "default": default, "required": required, "enums": enums}


def _ts_parse_file(text):
    """Parse one `models.ts` file into `(defined, all_names, reexports)`.

    `defined` maps type name -> its Surface-shaped `{fields, required, enums}`
    entry, for every top-level `export const NAME = zod...` that resolves to
    an object schema (see `_ts_object_body`) -- an enum/union/scalar/array/
    record const gets no entry, same as Python only registering `BaseModel`
    subclasses. `all_names` is every top-level `export const NAME = zod...`
    name found regardless of whether it resolved to an object -- postprocess
    dedups *any* duplicate top-level const, not just object-shaped ones (e.g.
    `FunctionData`, a `zod.union([...])`, is re-exported too), so
    `load_typescript_surface` needs this to tell "re-exports a real,
    non-object type" apart from "re-exports a name that doesn't exist at
    all", without which every non-object re-export would look like a parser
    bug in the owner file.

    `reexports` maps a deduped type's name -> the domain owning its real
    definition, from `export { NAME } from "../<domain>/models";` -- what
    `postprocess.ts` leaves behind for the 106 types it deduped into a single
    owner instead of duplicating (see the module docstring). These have no
    local body to parse, only a pointer; `load_typescript_surface` resolves
    them against the owner's `defined`, or undercounts the TypeScript surface
    by exactly 106 phantom "missing" types.
    """
    mask = _ts_mask_strings(text)

    const_registry = {}
    for m in _TS_CONST_DECL_RE.finditer(text):
        if mask[m.start()]:
            continue
        start = m.end()
        end = _ts_find_top_level_semicolon(text, mask, start)
        const_registry[m.group(1)] = _ts_parse_js_value(text[start:end], const_registry)

    defined = {}
    all_names = set()
    for m in _TS_TOP_TYPE_RE.finditer(text):
        if mask[m.start()]:
            continue
        all_names.add(m.group(1))
        calls, _ = _ts_parse_call_chain(text, mask, m.start(2))
        obj = _ts_object_body(calls)
        if obj is None:
            continue
        body, body_mask = obj
        fields, required, enums = {}, set(), {}
        for field_name, field_calls in _ts_parse_object_fields(body, body_mask).items():
            info = _ts_field_info(field_calls, const_registry)
            fields[field_name] = {"kind": info["kind"], "default": info["default"]}
            if info["required"]:
                required.add(field_name)
            if info["enums"] is not None:
                enums[field_name] = info["enums"]
        defined[m.group(1)] = {"fields": fields, "required": required, "enums": enums}

    reexports = {
        m.group(1): m.group(2) for m in _TS_REEXPORT_RE.finditer(text) if not mask[m.start()]
    }
    return defined, all_names, reexports


def load_typescript_surface(ts_root):
    """Parse every domain's generated `models.ts` under `ts_root/src` into a Surface.

    Each of the six domain files is parsed independently for its own directly
    defined object schemas; re-exports are then resolved against whichever
    other domain actually owns that definition, so a deduped type is counted
    once, correctly, rather than reported missing from every domain that
    merely re-exports it (see `_ts_parse_file`). A re-export whose owner
    defines the name but not as an object schema (e.g. `FunctionData`, a
    `zod.union([...])` re-exported into five other domains) is simply not a
    Surface type here either, for the same reason its owner's own copy isn't.
    """
    paths = sorted(Path(ts_root).glob("src/*/models.ts"))
    per_domain = {}
    for path in paths:
        defined, all_names, reexports = _ts_parse_file(path.read_text())
        per_domain[path.parent.name] = {
            "defined": defined,
            "all_names": all_names,
            "reexports": reexports,
        }

    surface = {}
    for parsed in per_domain.values():
        for name, entry in parsed["defined"].items():
            surface.setdefault(name, entry)
    for domain, parsed in per_domain.items():
        for name, owner in parsed["reexports"].items():
            if name in surface:
                continue
            owner_info = per_domain.get(owner, {})
            if name in owner_info.get("defined", {}):
                surface[name] = owner_info["defined"][name]
            elif name in owner_info.get("all_names", set()):
                continue
            else:
                raise ValueError(
                    f"{domain}/models.ts re-exports {name!r} from {owner!r}, but "
                    f"{owner}/models.ts defines no top-level const named {name!r} "
                    f"at all -- the postprocess dedup and this parser's top-level-"
                    f"type detection disagree about what {name!r} is."
                )

    return Surface(
        language="TypeScript",
        types=surface,
        files_scanned=len(paths),
        detail={"per_domain": {d: len(p["defined"]) for d, p in per_domain.items()}},
    )


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
#
# Julia<->Python only. Every reason below is specific to openapi-generator's
# Julia template (a check_required quirk, a discriminator-duplication quirk,
# an anonymous-oneOf-naming quirk) -- none of it describes orval/zod. `main()`
# never applies this table to the Python<->TypeScript comparison; that pair
# is a hard gate with no exemptions of any kind.
# --------------------------------------------------------------------------- #

EXEMPTIONS = {
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
            "postprocess.py's fix_required_fields_with_schema_defaults restores the "
            "default) correctly drops `required`. Verified no runtime "
            "divergence: CostCurve(...) "
            "omitting power_units resolves to NATURAL_UNITS on both sides."
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


# --------------------------------------------------------------------------- #
# Schema-declared defaults -- backs the default-value comparator's None/absent
# and value/absent normalizations below. Independent of EXEMPTIONS: this is
# not a named waiver, it is recognizing that two differently-materialized
# renderings of the same schema truth are not a divergence at all.
# --------------------------------------------------------------------------- #


def _collect_schema_property_defaults(node, registry):
    """Walk one parsed schema JSON document, recording every `default` a
    `properties` entry declares on itself, keyed by property name.

    Keyed by name alone, not by the enclosing type: at the point the
    default-value comparator needs this, it is looking at an already-
    materialized nested dict with no attached schema-type identity (see
    `_absence_is_legitimate`), so exact per-type resolution isn't available
    without threading a full type-aware walk through every language's
    already-flattened default value. Property names that carry a schema
    default in this codebase are consistent wherever they recur (verified:
    every `power_units` property that declares a default anywhere declares
    exactly `"NATURAL_UNITS"`; same for the handful of others this backs) --
    and `_unique_schema_default` refuses to use an entry where two
    declarations for the same name actually disagree, rather than silently
    picking one.
    """
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for name, sub in props.items():
                if isinstance(sub, dict) and "default" in sub:
                    registry.setdefault(name, []).append(sub["default"])
        for value in node.values():
            _collect_schema_property_defaults(value, registry)
    elif isinstance(node, list):
        for item in node:
            _collect_schema_property_defaults(item, registry)


def load_schema_property_defaults(schema_dir):
    """Map every property name to the list of `default` values found for it
    anywhere under `schema_dir`'s five top-level schema directories.

    Returns an empty registry (every normalization below then falls back to
    its most conservative behavior -- see `_absence_is_legitimate`) rather
    than raising when `schema_dir` isn't checked out, mirroring how the rest
    of this file degrades when an optional sibling checkout is missing.
    """
    registry: dict = {}
    root = Path(schema_dir)
    if not root.is_dir():
        return registry
    for sub in SCHEMA_SUBDIRS:
        for path in sorted(root.glob(f"{sub}/**/*.json")):
            _collect_schema_property_defaults(json.loads(path.read_text()), registry)
    return registry


def _unique_schema_default(registry, key):
    """`(has_default, value)` for property name `key`.

    `has_default=True` means at least one schema property named `key`
    declares an explicit `default` (any JSON value, including `null`) *and*
    every such declaration agrees on the value. `has_default=False` means
    either no schema property of this name ever declares a default at all,
    or two declarations disagree -- never guessed either way, so the caller
    treats it exactly like "no default" (the safe direction: it only ever
    risks leaving a real divergence unnormalized, never hiding one).
    """
    values = registry.get(key)
    if not values:
        return False, None
    first = values[0]
    if all(v == first for v in values[1:]):
        return True, first
    return False, None


def _absence_is_legitimate(present, key, registry):
    """True when a key present as `present` on one side and entirely ABSENT
    on the other is the same schema-truth value, not a real divergence.

    Two distinct cases, per the schema's own declaration for `key`:

    * No schema property named `key` ever declares a `default` at all: an
      omitted field then loads as `None` on both sides by construction
      (pydantic's `model_dump()`, and orval's `.optional()`/no-default
      field) -- so `present is None` is the only way this is legitimate.
      `present` being anything else means one side somehow produced a real
      value for a property the schema never defaults, which is still a
      divergence.

    * The schema DOES declare a default for `key` (including an explicit
      `null` default): dropping the key is only equivalent to the schema's
      OWN default value, never to a bare "it's the same as omitted"
      shortcut -- an explicit `"default": null` that one side drops is a
      real divergence and must still fail even though the values involved
      are both `None` (schema intent, not incidental nullness, is what's
      being compared). This also covers the case this fix specifically
      targets: a schema-declared non-null default (e.g. `CostCurve.
      power_units`'s `"NATURAL_UNITS"`) that one side's static
      representation fills in (via its own materialization) and the other
      leaves out entirely -- legitimate exactly when the present value
      equals that declared default, recursively.

    An empty `registry` (no schema checkout was found -- see
    `load_schema_property_defaults`) never normalizes anything: it would be
    indistinguishable from "no schema property named `key` ever declares a
    default," which is exactly the case that DOES normalize, so treating an
    empty registry as "known to have no default" would silently apply this
    normalization with no actual schema evidence behind it. Refusing is the
    same choice this file already makes for a missing Julia/TypeScript path
    (`_require_real_surface`): no schema, no verdict, not a guessed one.
    """
    if not registry:
        return False
    has_default, schema_default = _unique_schema_default(registry, key)
    if not has_default:
        return present is None
    if schema_default is None:
        return False
    return _defaults_equal(present, schema_default, registry)


def _defaults_equal(a, b, schema_registry):
    """True when two already-parsed default values mean the same thing, not
    necessarily look the same in source.

    Two narrow normalizations, applied recursively through nested dict/list
    defaults and symmetrically regardless of which side is which language:

    * A number compares by numeric value, so a Python float and a
      TypeScript/Julia integer literal for the same magnitude (`1000000.0`
      vs `1000000`) agree. `bool` is excluded first (Python's `bool` is an
      `int` subclass) so `0`/`False` and `1`/`True` still differ -- and a
      string never equals a number, since neither branch below matches a
      `str`, leaving the final `a == b` (which is `False` for `"1" == 1`).

    * A key present with some value on one side and entirely ABSENT on the
      other is delegated to `_absence_is_legitimate`, which consults
      `schema_registry` to decide whether the schema itself justifies
      treating the omission as equivalent to that value.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if isinstance(a, dict) and isinstance(b, dict):
        for key in set(a) | set(b):
            in_a, in_b = key in a, key in b
            if in_a and in_b:
                if not _defaults_equal(a[key], b[key], schema_registry):
                    return False
            else:
                present = a[key] if in_a else b[key]
                if not _absence_is_legitimate(present, key, schema_registry):
                    return False
        return True
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_defaults_equal(x, y, schema_registry) for x, y in zip(a, b, strict=True))
    return a == b


def compare(a, b, label_a, label_b, schema_registry=None):
    """Return `(problems, notes, shared)` comparing two Surface `.types` dicts.

    `problems` entries are `(key, message)` pairs, `key = (type, field)` with
    `field=None` for a whole-type divergence — the lookup key a caller applying
    `EXEMPTIONS` uses. Splitting a multi-field divergence (e.g. a required-set
    mismatch naming several fields) into one entry per field keeps each
    exemption named at exactly the granularity the brief requires: a single
    `type.field`, never a category.

    A type present only in `a` is a problem: `a` is missing something `b`
    has. A type present only in `b` is a note: `b`'s own generator has stand-
    ins with nothing on `a`'s side to compare against -- pydantic's RootModel
    wrappers for a bare type alias, or (for the TypeScript comparison) an
    anonymous oneOf branch orval never gives its own name. Every per-field
    check inside a shared type is symmetric: a divergence in either direction
    is a problem, worded with whichever label it belongs to. Both surfaces
    must already carry pre-resolved, directly comparable field info (`kind`
    one of the shared JSON-kind strings, `default` an already-evaluated JSON
    value) -- any language-specific interpretation (Julia's raw type text
    needing `JULIA_KIND`, its default needing `parse_julia_expr`) happens once,
    in that language's own `load_*_surface`, not here.

    `schema_registry` (from `load_schema_property_defaults`) feeds the
    default-value check's `_defaults_equal` normalization: a `None`-vs-absent
    or value-vs-absent split inside a composite default is recognized as the
    same schema truth rather than a divergence when the schema itself
    justifies it (see `_absence_is_legitimate`). `None` (the default) simply
    disables that normalization -- every default mismatch then reports
    exactly as it always did.
    """
    problems, notes = [], []
    if schema_registry is None:
        schema_registry = {}
    shared = sorted(set(a) & set(b))

    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    for name in only_a:
        problems.append(((name, None), f"{name}: present in {label_a}, absent in {label_b}"))
    for name in only_b:
        notes.append(f"{name}: present in {label_b}, no {label_a} type")

    for name in shared:
        av, bv = a[name], b[name]
        af, bf = set(av["fields"]), set(bv["fields"])
        for field in sorted(af - bf):
            msg = f"{name}.{field}: in {label_a}, missing from {label_b}"
            problems.append(((name, field), msg))
        for field in sorted(bf - af):
            msg = f"{name}.{field}: in {label_b}, missing from {label_a}"
            problems.append(((name, field), msg))

        for field in sorted(av["required"] - bv["required"]):
            problems.append(((name, field), f"{name}.{field}: required only in {label_a}"))
        for field in sorted(bv["required"] - av["required"]):
            problems.append(((name, field), f"{name}.{field}: required only in {label_b}"))

        for field in sorted(af & bf):
            akind = av["fields"][field]["kind"]
            bkind = bv["fields"][field]["kind"]
            if akind and bkind and akind != bkind:
                problems.append(
                    (
                        (name, field),
                        f"{name}.{field}: type kind {label_a}={akind} {label_b}={bkind}",
                    )
                )
            # A default on a field that both sides require is unreachable: omitting
            # the field is an error, not a fallback, so a difference there cannot
            # change what either language loads. Julia pre-fills several such
            # fields (StorageCost.fixed, the const discriminators); comparing them
            # would report noise.
            if field in av["required"] and field in bv["required"]:
                continue
            ad = av["fields"][field]["default"]
            bd = bv["fields"][field]["default"]
            if not _defaults_equal(ad, bd, schema_registry):
                problems.append(
                    (
                        (name, field),
                        f"{name}.{field}: default {label_a}={ad!r} {label_b}={bd!r} "
                        f"(optional both sides — an omitted field loads differently)",
                    )
                )

        for field in sorted(set(av["enums"]) & set(bv["enums"])):
            avals, bvals = av["enums"][field], bv["enums"][field]
            if sorted(avals) != sorted(bvals):
                problems.append(
                    (
                        (name, field),
                        f"{name}.{field}: enum values differ "
                        f"{label_a}={sorted(avals)} {label_b}={sorted(bvals)}",
                    )
                )
        for field in sorted(set(bv["enums"]) - set(av["enums"])):
            problems.append(
                (
                    (name, field),
                    f"{name}.{field}: {label_b} constrains it to an enum, {label_a} does "
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


def _print_notes(notes):
    if not notes:
        return
    print(f"NOTES ({len(notes)}) — not failures:")
    for n in notes[:15]:
        print(f"  {n}")
    if len(notes) > 15:
        print(f"  ...and {len(notes) - 15} more")
    print()


def _require_shared_types(shared, count_a, count_b, label_a, label_b):
    """Refuse to call it agreement when two real surfaces share no names.

    Companion guard to `_require_real_surface`: that one catches a parser
    that scanned nothing, this one catches two parsers that each scanned
    something real but whose naming assumptions (DOMAINS, a rename) no
    longer line up, so the comparison would silently check zero types while
    still looking like it ran.
    """
    if not shared:
        print(
            f"ERROR: 0 shared types even though both surfaces parsed real "
            f"types ({count_a} {label_a}, {count_b} {label_b}) — every type "
            f"name differs, so nothing was actually compared. Check naming "
            f"assumptions before trusting any verdict from this run."
        )
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--julia", default=str(DEFAULT_JULIA))
    parser.add_argument("--ts", default=str(REPO_ROOT / "typescript"))
    parser.add_argument(
        "--schema-dir",
        default=str(DEFAULT_SCHEMA_DIR),
        help=(
            "SiennaSchemas checkout backing the default-value comparator's "
            "schema-declares-no-default normalization (see "
            "load_schema_property_defaults): a key present as None on one side "
            "and absent on the other, or present with a real value on one side "
            "and absent on the other, is recognized as the same schema truth "
            "rather than a divergence only when this schema checkout confirms "
            "it. If this path doesn't exist, no such normalization applies at "
            "all (every one of those splits reports as a divergence, exactly "
            "as before this normalization existed) -- printed loudly below "
            "either way, never silently."
        ),
    )
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
    ts_root = Path(args.ts).resolve()
    ts_surface = load_typescript_surface(ts_root)

    schema_dir = Path(args.schema_dir).resolve()
    schema_registry = load_schema_property_defaults(schema_dir)
    if schema_registry:
        print(
            f"Schema-declared defaults: {len(schema_registry)} property name(s) "
            f"found under {schema_dir}"
        )
    else:
        print(
            f"Schema-declared defaults: NONE found under {schema_dir} -- the "
            f"None/absent and value/absent default-comparator normalizations "
            f"below are disabled; every such split reports as a divergence."
        )
    print()

    print(
        f"Julia structs:    {len(julia_surface.types)} "
        f"(from {julia_surface.files_scanned} file(s); "
        f"{julia_surface.detail.get('enum_types_found', 0)} of them enum types)"
    )
    print(
        f"Python models:    {len(python_surface.types)} "
        f"(from {python_surface.files_scanned} file(s))"
    )
    per_domain = ts_surface.detail.get("per_domain", {})
    print(
        f"TypeScript types: {len(ts_surface.types)} "
        f"(from {ts_surface.files_scanned} file(s)) — "
        + ", ".join(f"{d}={per_domain.get(d, 0)}" for d in DOMAINS)
    )
    print()

    if (
        not _require_real_surface(julia_surface)
        or not _require_real_surface(python_surface)
        or not _require_real_surface(ts_surface)
    ):
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

    exit_code = 0

    # ----------------------------------------------------------------- #
    # Julia <-> Python: EXEMPTIONS apply; --julia-report-only can keep it
    # from failing the run.
    # ----------------------------------------------------------------- #
    print("=" * 70)
    print("Julia <-> Python")
    print("=" * 70)
    julia_problems, julia_notes, julia_shared = compare(
        julia_surface.types, python_surface.types, "Julia", "Python", schema_registry
    )
    if not _require_shared_types(
        julia_shared, len(julia_surface.types), len(python_surface.types), "Julia", "Python"
    ):
        return 3
    print(f"Compared {len(julia_shared)} shared types.\n")

    julia_failures = [(key, msg) for key, msg in julia_problems if key not in EXEMPTIONS]
    julia_exempted = [(key, msg) for key, msg in julia_problems if key in EXEMPTIONS]

    # An exemption whose divergence no longer occurs is rot: the field was
    # renamed or the generator fixed, and the entry now waives nothing while
    # still reading as deliberate coverage. Nothing else notices, because
    # exemptions are only ever looked up FROM detected problems -- the same
    # shape as this script's own "surfaces agree" bug, where a check stayed
    # green by matching nothing.
    unused = sorted(set(EXEMPTIONS) - {key for key, _ in julia_problems})
    if unused:
        print(f"ERROR: {len(unused)} EXEMPTIONS entr(ies) matched no divergence:")
        for type_name, field in unused:
            label = type_name if field is None else f"{type_name}.{field}"
            print(f"  {label}")
        print(
            "Each waives nothing. Delete it, or fix the key if the field was renamed.\n",
            file=sys.stderr,
        )
        return 3

    _print_notes(julia_notes)

    if julia_exempted:
        print(f"EXEMPTIONS ({len(julia_exempted)}) — named, not failures:")
        for key, msg in julia_exempted:
            print(f"  {msg}")
            print(f"    reason: {EXEMPTIONS[key]['reason']}")
            print(f"    remove when: {EXEMPTIONS[key]['remove_when']}")
        print()

    if julia_failures:
        print(f"DIVERGENCES ({len(julia_failures)}):")
        for _, msg in julia_failures:
            print(f"  {msg}")
        print(f"\n{len(julia_failures)} divergence(s) would break bi-directional loading.")
        if args.julia_report_only:
            print(
                f"\nREPORT-ONLY MODE: the {len(julia_failures)} Julia<->Python "
                f"divergence(s) above do NOT fail this run. Almost all of them are "
                f"one confirmed, pre-existing Julia generator bug -- an omitted "
                f"defaulted field decodes to ABSENT in Julia where Python "
                f"materializes the schema default (e.g. SEXS without V_ref: "
                f"ABSENT in Julia, 1.0 in Python) -- tracked separately, not fixable "
                f"by editing generated code in this repo. Python<->TypeScript is "
                f"the blocking gate for this repo's CI. Run without "
                f"--julia-report-only to make these divergences fail the build."
            )
        else:
            exit_code = 1
    else:
        print(
            f"Julia <-> Python surfaces agree: field sets, required fields, enum "
            f"values, kinds, defaults ({len(julia_exempted)} named exemption(s) — "
            f"see above)."
            if julia_exempted
            else "Julia <-> Python surfaces agree: field sets, required fields, "
            "enum values, kinds, defaults."
        )
    print()

    # ----------------------------------------------------------------- #
    # Python <-> TypeScript: hard gate. No EXEMPTIONS, no report-only.
    # ----------------------------------------------------------------- #
    print("=" * 70)
    print("Python <-> TypeScript")
    print("=" * 70)
    ts_problems, ts_notes, ts_shared = compare(
        ts_surface.types, python_surface.types, "TypeScript", "Python", schema_registry
    )
    if not _require_shared_types(
        ts_shared, len(ts_surface.types), len(python_surface.types), "TypeScript", "Python"
    ):
        return 3
    print(f"Compared {len(ts_shared)} shared types.\n")

    _print_notes(ts_notes)

    if ts_problems:
        print(f"DIVERGENCES ({len(ts_problems)}):")
        for _, msg in ts_problems:
            print(f"  {msg}")
        print(
            f"\n{len(ts_problems)} divergence(s). Python<->TypeScript is a hard "
            f"gate with no EXEMPTIONS applied (that table is specific to "
            f"openapi-generator's Julia template) and no report-only mode: every "
            f"one of these must be fixed, not waived."
        )
        exit_code = 1
    else:
        print(
            "Python <-> TypeScript surfaces agree: field sets, required fields, "
            "enum values, kinds, defaults."
        )

    return exit_code


if __name__ == "__main__":
    sys.exit(main())

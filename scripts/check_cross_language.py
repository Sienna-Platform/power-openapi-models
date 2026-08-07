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
this runs without a Julia install: `Base.@kwdef mutable struct` for fields and
defaults, `check_required` for required fields, and the `validate_param(...,
:enum, ...)` calls for allowed values.

One asymmetry is structural rather than a defect, and is reported separately as
NOTE: Julia emits each schema enum as `const X = String` and enforces the allowed
values inside `OpenAPI.validate_property`, so an invalid value is caught only
when the caller validates. Pydantic makes it an `Enum` and rejects it during
construction. Both honour the schema; only Julia can be bypassed.

Exit status is non-zero when a real divergence is found, so this is usable as a
gate. NOTEs alone do not fail the run.
"""

import argparse
import importlib
import re
import sys
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JULIA = REPO_ROOT / ".." / "PowerOpenAPIModels"
DOMAINS = ("core", "operations", "investments", "dynamics")

# Julia scalar -> the JSON kind it serializes as, for comparing against pydantic.
JULIA_KIND = {
    "Int64": "integer",
    "Float64": "number",
    "String": "string",
    "Bool": "boolean",
}
PY_KIND = {int: "integer", float: "number", str: "string", bool: "boolean"}


# --------------------------------------------------------------------------- #
# Julia side: parse the generated sources
# --------------------------------------------------------------------------- #


def parse_julia_model(text):
    """Extract one generated model's surface, or None if the file defines no struct."""
    struct = re.search(
        r"Base\.@kwdef mutable struct (\w+) <: OpenAPI\.APIModel\n(.*?)\n\s*function ",
        text,
        re.DOTALL,
    )
    if struct is None:
        return None
    name, body = struct.group(1), struct.group(2)

    fields = {}
    for raw_line in body.splitlines():
        # A field can carry both an annotation and a trailing spec-type comment:
        #     cofire_start_limits::Union{Nothing, Dict} = nothing # spec type: ...
        # Keep the comment only when it is the sole source of the type.
        line = raw_line
        if "::" in raw_line.split("#", 1)[0]:
            line = raw_line.split("#", 1)[0].rstrip()
        # Two shapes. Scalars carry the annotation inline:
        #     angle::Union{Nothing, Float64} = nothing
        # while a $ref-typed field is emitted untyped, with the type in a
        # trailing comment, so it must be read from there:
        #     voltage_limits = nothing # spec type: Union{ Nothing, MinMax }
        m = re.match(
            r"\s*(\w+)::Union\{Nothing,\s*(.+?)\}\s*(?:=\s*(.+?))?\s*$", line
        )
        if m is not None:
            field, jtype, default = m.group(1), m.group(2).strip(), m.group(3)
        else:
            m = re.match(
                r"\s*(\w+)\s*=\s*(.+?)\s*#\s*spec type:\s*Union\{\s*Nothing,\s*(.+?)\s*\}\s*$",
                line,
            )
            if m is None:
                continue
            field, default, jtype = m.group(1), m.group(2), m.group(3).strip()
        if default is not None:
            default = default.strip().rstrip(",")
            if default == "nothing":
                default = None
        fields[field] = {"type": jtype, "default": default}

    required = set(
        re.findall(r"o\.(\w+) === nothing && \(return false\)", text)
    )
    enums = {}
    for m in re.finditer(
        r'validate_param\(name, "\w+", :enum, val, \[(.*?)\]\)', text, re.DOTALL
    ):
        values = re.findall(r'"([^"]*)"', m.group(1))
        # The enclosing `if name === Symbol("field")` names the field.
        prefix = text[: m.start()]
        field = re.findall(r'if name === Symbol\("(\w+)"\)', prefix)
        if field:
            enums[field[-1]] = values
    return name, {"fields": fields, "required": required, "enums": enums}


def load_julia_surface(julia_root):
    """Map type name -> surface, across all generated Julia packages."""
    surface = {}
    aliases = {}
    for models_dir in sorted(Path(julia_root).glob("*.jl/src/models")):
        for path in sorted(models_dir.glob("model_*.jl")):
            text = path.read_text()
            alias = re.search(r"const (\w+) = String", text)
            if alias is not None:
                aliases[alias.group(1)] = "String"
            parsed = parse_julia_model(text)
            if parsed is not None:
                surface.setdefault(parsed[0], parsed[1])
    return surface, aliases


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
    for domain in DOMAINS:
        module = importlib.import_module(f"power_openapi_models.{domain}.models")
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
    return surface


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


def compare(julia, python):
    problems, notes = [], []
    shared = sorted(set(julia) & set(python))

    only_julia = sorted(set(julia) - set(python))
    only_python = sorted(set(python) - set(julia))
    for name in only_julia:
        problems.append(f"{name}: present in Julia, absent in Python")
    for name in only_python:
        # Pydantic exposes helper models (RootModel wrappers) Julia has no struct
        # for; report as a note so real gaps stay visible.
        notes.append(f"{name}: present in Python, no Julia struct")

    for name in shared:
        j, p = julia[name], python[name]
        jf, pf = set(j["fields"]), set(p["fields"])
        for field in sorted(jf - pf):
            problems.append(f"{name}.{field}: in Julia, missing from Python")
        for field in sorted(pf - jf):
            problems.append(f"{name}.{field}: in Python, missing from Julia")

        if j["required"] != p["required"]:
            jonly = sorted(j["required"] - p["required"])
            ponly = sorted(p["required"] - j["required"])
            if jonly:
                problems.append(f"{name}: required only in Julia: {jonly}")
            if ponly:
                problems.append(f"{name}: required only in Python: {ponly}")

        for field in sorted(jf & pf):
            jkind = JULIA_KIND.get(j["fields"][field]["type"])
            pkind = p["fields"][field]["kind"]
            if jkind and pkind and jkind != pkind:
                problems.append(
                    f"{name}.{field}: type kind Julia={jkind} Python={pkind}"
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
                    f"{name}.{field}: default Julia={jd!r} Python={pd!r} "
                    f"(optional both sides — an omitted field loads differently)"
                )

        for field in sorted(set(j["enums"]) & set(p["enums"])):
            jv, pv = j["enums"][field], p["enums"][field]
            if sorted(jv) != sorted(pv):
                problems.append(
                    f"{name}.{field}: enum values differ "
                    f"Julia={sorted(jv)} Python={sorted(pv)}"
                )
        for field in sorted(set(p["enums"]) - set(j["enums"])):
            problems.append(
                f"{name}.{field}: Python constrains it to an enum, Julia does not "
                f"validate it at all"
            )
    return problems, notes, shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--julia", default=str(DEFAULT_JULIA))
    args = parser.parse_args()

    julia_root = Path(args.julia).resolve()
    if not julia_root.is_dir():
        print(f"Julia package tree not found: {julia_root}")
        return 2

    julia, aliases = load_julia_surface(julia_root)
    python = load_python_surface()
    print(f"Julia structs:  {len(julia)}")
    print(f"Python models:  {len(python)}")
    print(f"Julia enums emitted as bare String aliases: {len(aliases)}\n")

    problems, notes, shared = compare(julia, python)
    print(f"Compared {len(shared)} shared types.\n")

    if notes:
        print(f"NOTES ({len(notes)}) — not failures:")
        for n in notes[:15]:
            print(f"  {n}")
        if len(notes) > 15:
            print(f"  ...and {len(notes) - 15} more")
        print()

    if problems:
        print(f"DIVERGENCES ({len(problems)}):")
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} divergence(s) would break bi-directional loading.")
        return 1

    print("Surfaces agree: field sets, required fields, enum values, kinds, defaults.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

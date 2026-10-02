"""Hand-written (NOT generated): the schema-version reader rule and the strict-bundle
check behind `write_document(..., schema_version="source")`.

The rule, its outcomes and the canonical message texts are defined once, in
SiennaSchemas' `docs/VERSIONING.md`; `scripts/schema_version.py` there is the reference
implementation. `check_schema_version` must agree with `tests/fixtures/versioning/cases.json`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

Outcome = Literal["missing", "malformed", "incompatible", "newer", "upgradable", "current"]

READER_VERSION = (
    (Path(__file__).parent / "_schema_version.txt").read_text().strip().removeprefix("v")
)
BUNDLE_DIR = Path(__file__).parent / "bundles"

_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?")


class SchemaVersionError(ValueError):
    """A document whose `schema_version` this reader cannot read."""

    def __init__(self, outcome: Outcome, reader: str, document: object, message: str):
        super().__init__(message)
        self.outcome = outcome
        self.reader = reader
        self.document = document


def _parse(version: object) -> tuple[tuple[int, str], ...] | None:
    """Components as (digit count, digits): the pattern forbids leading zeros, so this
    orders like the integers without a size limit."""
    if not isinstance(version, str):
        return None
    m = _PATTERN.fullmatch(version)
    if m is None:
        return None
    pre = (0, m[4][1:]) if m[4] else (0, "")
    return (*((len(m[i]), m[i]) for i in (1, 2, 3)), pre)


def _prerelease(version) -> bool:
    return bool(version[3][1])


def _line(version) -> tuple[tuple[int, str], ...]:
    major, minor = version[:2]
    return (major, minor) if major[1] == "0" else (major,)


def _line_name(version) -> str:
    return ".".join(digits for _, digits in _line(version))


def _classify(raw: object, reader: str) -> Outcome:
    if not isinstance(raw, dict):
        raise ValidationError.from_exception_data(
            "document", [{"type": "dict_type", "loc": (), "input": raw}]
        )
    if "schema_version" not in raw:
        return "missing"
    d = _parse(raw["schema_version"])
    if d is None:
        return "malformed"
    r = _parse(reader)
    if r is None:
        raise ValueError(f"reader schema version {reader!r} is not a valid version")
    if (_prerelease(d) or _prerelease(r)) and d != r:
        return "incompatible"
    if _line(d) != _line(r):
        return "incompatible"
    if d[:3] > r[:3]:
        return "newer"
    if d[:3] < r[:3]:
        return "upgradable"
    return "current"


def _message(outcome: Outcome, reader: str, document: object) -> str:
    if outcome == "missing":
        return (
            "document has no schema_version: it predates versioning; re-export it with a "
            "current producer (psy5 bundles: PowerSystemsUpdater)"
        )
    if outcome == "malformed":
        encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
        return f"document schema_version {encoded} is not a valid version"
    d = _parse(document)
    r = _parse(reader)
    assert d is not None and r is not None
    if outcome == "incompatible":
        if _prerelease(d) or _prerelease(r):
            return (
                f"document written by schema {document} cannot be read by schema {reader}: "
                "dev builds read only their own output"
            )
        return (
            f"document written by schema {document} (line {_line_name(d)}) cannot be read by "
            f"schema {reader} (line {_line_name(r)}): documents do not cross compatibility "
            "lines; migrating between lines is a separate upgrade tool's job "
            "(psy5 bundles: PowerSystemsUpdater)"
        )
    return (
        f"document written by schema {document}; this reader understands up to {reader}; "
        f"update the model package to one built from >= {document}"
    )


def _check(raw: object, reader: str) -> Outcome:
    outcome = _classify(raw, reader)
    if outcome in ("upgradable", "current"):
        return outcome
    document = raw.get("schema_version")
    raise SchemaVersionError(outcome, reader, document, _message(outcome, reader, document))


def check_schema_version(raw: object) -> Outcome:
    """Classify the raw parsed JSON of a document against this package's schema version.

    Pure: returns the outcome and never raises `SchemaVersionError` (the read path does).
    A non-object root is a format error and raises pydantic's `ValidationError`, as
    reading it does. Run before decoding, so a newer document reports its version
    rather than an unknown key.
    """
    return _classify(raw, READER_VERSION)


def _covered(error, branch: int, root: dict) -> int:
    """How many instance keys the `branch` of an anyOf/oneOf `error` declares."""
    sub = error.schema[error.validator][branch]
    while "$ref" in sub:
        node = root
        for part in sub["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        sub = node
    if not isinstance(error.instance, dict):
        return 0
    return sum(1 for key in error.instance if key in sub.get("properties", {}))


def _leaves(error, root: dict):
    """The offending (path, message) pairs under one validation error."""
    if error.validator in ("anyOf", "oneOf") and error.context:
        branches: dict[int, list] = {}
        for e in error.context:
            branches.setdefault(e.schema_path[0], []).extend(_leaves(e, root))
        pick = min(
            branches,
            key=lambda i: (len(branches[i]), -_covered(error, i, root)),
        )
        yield from branches[pick]
        return
    path = "/" + "/".join(str(p) for p in error.absolute_path)
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        known = error.schema.get("properties", {})
        for key in error.instance:
            if key not in known:
                yield f"{path.rstrip('/')}/{key}", "is not a property of this schema version"
        return
    yield path, error.message


def validate_source(tree: dict, document: str, bundle_name: str, bundle_dir: Path) -> None:
    """Validate the encoded `tree` against the strict bundle of schema `document`.

    Raises one `ValueError` listing every offending path.
    """
    try:
        from jsonschema import Draft7Validator
    except ImportError as e:
        raise ImportError(
            f"writing at the source schema version {document} needs a validator; "
            "install power-openapi-models[source-version]"
        ) from e
    bundle = Path(bundle_dir) / document / f"{bundle_name}.json"
    if not bundle.is_file():
        raise FileNotFoundError(f"strict bundle for schema {document} not found at {bundle}")
    root = json.loads(bundle.read_text())
    found = sorted(
        {leaf for e in Draft7Validator(root).iter_errors(tree) for leaf in _leaves(e, root)}
    )
    if found:
        lines = "\n".join(f"  {path}: {message}" for path, message in found)
        raise ValueError(
            f'document does not fit schema {document}; save with schema_version="current" '
            f"to write the current version:\n{lines}"
        )

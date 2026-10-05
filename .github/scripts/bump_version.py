#!/usr/bin/env python3
"""Bump every language manifest by the same level as a SiennaSchemas release.

  python3 .github/scripts/bump_version.py v0.1.0 v0.2.0

Prints the new version. The SDK mirrors the schema's bump LEVEL, not its number:
a schema minor bump is an SDK minor bump, a schema patch an SDK patch. The two
numbers drift apart once a generator-only fix ships as a hand-bumped SDK patch;
.schema-version records which schema each SDK version came from.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# (path, pattern matching the one version line). Each must match exactly once:
# a missed manifest is a release that publishes one language at a stale version.
MANIFESTS = [
    (REPO_ROOT / "python" / "pyproject.toml", r'^version = "{v}"$'),
    (REPO_ROOT / "typescript" / "package.json", r'^  "version": "{v}",$'),
    (REPO_ROOT / "rust" / "Cargo.toml", r'^version = "{v}"$'),
]

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def parse_tag(tag: str) -> tuple[int, int, int]:
    match = TAG.match(tag)
    if match is None:
        fail(f"{tag!r} is not a vMAJOR.MINOR.PATCH release tag")
    return tuple(int(part) for part in match.groups())


def bumped(version: str, old_tag: str, new_tag: str) -> str:
    old, new = parse_tag(old_tag), parse_tag(new_tag)
    if new <= old:
        fail(f"schema {new_tag} is not newer than {old_tag}")
    major, minor, patch = (int(part) for part in version.split("."))
    if new[0] > old[0]:
        return f"{major + 1}.0.0"
    if new[1] > old[1]:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    if len(sys.argv) != 3:
        fail("usage: bump_version.py <old schema tag> <new schema tag>")
    old_tag, new_tag = sys.argv[1:]

    pyproject = MANIFESTS[0][0].read_text()
    current = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE).group(1)
    new = bumped(current, old_tag, new_tag)

    for path, pattern in MANIFESTS:
        text, count = re.subn(
            pattern.format(v=re.escape(current)),
            lambda m: m.group(0).replace(current, new),
            path.read_text(),
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            fail(f"{path.relative_to(REPO_ROOT)}: no version line for {current}")
        path.write_text(text)

    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())

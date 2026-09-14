#!/usr/bin/env python3
"""Assert every language package declares the same version, and optionally that a
release tag matches it.

  python3 scripts/check_version_sync.py
  python3 scripts/check_version_sync.py --tag v0.1.0

Versioning here is LOCKSTEP: one version, one `v*` tag, fanned out to every
registry. That is only meaningful if the manifests cannot drift apart, and a
manifest is the one place a release can go wrong silently -- a tag that says
0.1.0 publishing a package.json that says 0.0.9 is a wrong artifact under a
right name, and nothing downstream can detect it.

Rust joins by adding an entry to MANIFESTS; nothing else here changes.
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (label, path, reader). A manifest that does not exist yet is skipped with a
# notice rather than failing: `rust/` is a prepared slot with no Cargo.toml, and
# typescript/package.json lands separately from this script.
MANIFESTS = [
    ("python", REPO_ROOT / "python" / "pyproject.toml", "pyproject"),
    ("typescript", REPO_ROOT / "typescript" / "package.json", "package_json"),
    ("rust", REPO_ROOT / "rust" / "Cargo.toml", "cargo"),
]


def read_package_json(path: Path) -> str:
    return json.loads(path.read_text())["version"]


def _read_toml_version(path: Path, section: str) -> str:
    """`[section].version` from a TOML file.

    The regex fallback exists because this repo supports Python 3.10, which has
    no tomllib. The version is a plain top-level key under a top-level table,
    so a scoped regex is exact here.
    """
    try:
        import tomllib
    except ImportError:
        match = re.search(
            rf"^\[{section}\]$.*?^version\s*=\s*[\"']([^\"']+)[\"']",
            path.read_text(),
            re.MULTILINE | re.DOTALL,
        )
        if match is None:
            fail(f"{path}: no [{section}] version found")
        return match.group(1)
    return tomllib.loads(path.read_text())[section]["version"]


def read_pyproject(path: Path) -> str:
    return _read_toml_version(path, "project")


def read_cargo(path: Path) -> str:
    return _read_toml_version(path, "package")


READERS = {
    "package_json": read_package_json,
    "pyproject": read_pyproject,
    "cargo": read_cargo,
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        help="Release tag to check against, e.g. v0.1.0. The leading 'v' is required.",
    )
    parser.add_argument(
        "--require",
        default="",
        help=(
            "Comma-separated labels that MUST be present, e.g. 'python,typescript'. "
            "Release workflows pass this: a manifest that is merely absent would "
            "otherwise be skipped, and a release that publishes nothing would pass "
            "a check named 'version sync'."
        ),
    )
    args = parser.parse_args()

    found = {}
    for label, path, kind in MANIFESTS:
        if not path.exists():
            print(f"  {label:<12} {path.relative_to(REPO_ROOT)}: not present, skipped")
            continue
        found[label] = READERS[kind](path)
        print(f"  {label:<12} {found[label]}")

    if not found:
        fail("no language manifests found at all -- this check compared nothing")

    required = [label for label in args.require.split(",") if label]
    missing = [label for label in required if label not in found]
    if missing:
        fail(f"required manifest(s) absent: {', '.join(missing)}")

    versions = set(found.values())
    if len(versions) > 1:
        detail = ", ".join(f"{label}={version}" for label, version in sorted(found.items()))
        fail(f"versions disagree across languages: {detail}")

    version = versions.pop()

    if args.tag:
        if not args.tag.startswith("v"):
            fail(f"tag {args.tag!r} does not start with 'v'")
        tag_version = args.tag[1:]
        if tag_version != version:
            fail(f"tag {args.tag} does not match the manifest version {version}")
        print(f"\nTag {args.tag} matches every manifest ({version}).")
    else:
        print(f"\nEvery manifest agrees: {version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

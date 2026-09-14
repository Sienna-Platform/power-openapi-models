#!/usr/bin/env python3
"""Enforce a floor on pyright's `--verifytypes` completeness score.

Plain `pyright --verifytypes <pkg>` is not a reliable pass/fail gate on its
own: its exit code reflects whether it printed *any* diagnostic, not whether
the completeness score cleared a bar. In this package roughly a third of the
"unknown type" symbols come from a demonstrated pyright/pydantic interaction
in `--verifytypes` mode specifically -- a minimal `class Foo(BaseModel): x:
int` in its own throwaway package reproduces the identical "Type of
metaclass unknown" / "Type of base class unknown" pair pyright reports for
every one of our generated models, even though a plain (non-`--verifytypes`)
pyright check of the same code resolves `pydantic.BaseModel` with zero
errors. That is a tooling artifact, not a gap in our annotations, and
`--ignoreexternal` does not remove it (these symbols are not classified as
external). Comparing against a fixed threshold makes the gate mean
something concrete -- a regression in our own annotations still fails it --
without chasing a tooling limitation to a 100% score that isn't achievable
today.

THRESHOLD is set a few points under the score measured when this script was
written (75.8%) so it fails on a real regression but tolerates the small
cross-version wobble the metaclass artifact itself introduces.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parent.parent
PACKAGE = "power_openapi_models"
THRESHOLD = 0.75


def main() -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PACKAGE_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", "--verifytypes", PACKAGE],
        cwd=PACKAGE_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        print("error: pyright did not emit parseable --outputjson output", file=sys.stderr)
        return 1

    completeness = report.get("typeCompleteness")
    if completeness is None:
        print(json.dumps(report, indent=2))
        print(
            f"error: no typeCompleteness section -- is {PACKAGE!r} resolvable with PYTHONPATH=src?",
            file=sys.stderr,
        )
        return 1

    score = completeness["completenessScore"]
    exported = completeness["exportedSymbolCounts"]
    print(
        f"{PACKAGE}: type completeness {score:.1%} "
        f"(known={exported['withKnownType']}, "
        f"ambiguous={exported['withAmbiguousType']}, "
        f"unknown={exported['withUnknownType']}, "
        f"threshold={THRESHOLD:.0%})"
    )

    if score < THRESHOLD:
        print(
            f"error: type completeness {score:.1%} is below the {THRESHOLD:.0%} floor",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

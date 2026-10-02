#!/usr/bin/env python3
"""Re-stamp the root fixtures' `schema_version` to the one pinned in `.schema-version`.

The fixtures are documents, and a reader rejects any stamp outside its own compatibility
line, so a schema bump that leaves them at the old stamp breaks every test that reads them.
Rewrites the stamp in place with a regex rather than a JSON dump: the files' formatting and
number literals stay byte-identical, and a no-op run leaves `git diff` unchanged.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = re.compile(r'^(  "schema_version": )"[^"]*"', re.MULTILINE)


def main() -> int:
    version = (ROOT / ".schema-version").read_text().strip().removeprefix("v")
    for path in sorted((ROOT / "fixtures").glob("case14_operations.*.json")):
        text = path.read_text()
        stamped, count = STAMP.subn(rf'\1"{version}"', text, count=1)
        if count != 1:
            print(f"{path}: no top-level schema_version to re-stamp", file=sys.stderr)
            return 1
        assert json.loads(stamped)["schema_version"] == version
        if stamped != text:
            path.write_text(stamped)
    return 0


if __name__ == "__main__":
    sys.exit(main())

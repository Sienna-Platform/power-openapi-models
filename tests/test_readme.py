"""Execute every fenced `python` block in the README.

The README shipped several false claims before 0.1.0 -- classes and modules
that never existed, a make target that never existed. Prose rots silently;
this makes it fail loudly instead. A block that should not run (illustrative
pseudo-code, a deliberate error) must be fenced as `text`, not `python`.

Run from the repo root (as the project's documented gate command does): the
worked-example block reads ``tests/fixtures/case14_operations.NATURAL_UNITS.json``
by a path relative to the current working directory, not to this file.
"""

import pathlib
import re

import pytest

README = pathlib.Path(__file__).parent.parent / "README.md"
BLOCK = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)


def readme_blocks():
    return list(enumerate(BLOCK.findall(README.read_text()), start=1))


@pytest.mark.parametrize("index,source", readme_blocks())
def test_readme_block_executes(index, source):
    try:
        exec(compile(source, f"README.md#block{index}", "exec"), {"__name__": "__main__"})
    except Exception as exc:
        pytest.fail(
            f"README python block {index} failed: {type(exc).__name__}: {exc}\n"
            f"--- block ---\n{source}"
        )


def test_readme_has_executable_blocks():
    """Guard the guard: a README with no python blocks would pass vacuously."""
    assert len(readme_blocks()) >= 4

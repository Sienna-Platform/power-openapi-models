"""Hand-written (NOT generated): the type the generated models use for
`format: date-time` fields.

The schemas say RFC 3339, which requires an offset, and datamodel-codegen emits
`AwareDatetime` for it, so `2024-01-01T00:00:00` was rejected. Real producers write
timestamps without an offset, so all three packages (Python, TypeScript, Rust) accept
one. A timestamp is kept as written: no offset gives a naive `datetime` (a wall
clock), and an offset gives an aware `datetime` with that offset. The SDK does not
assume a zone. A series' `time_reference` says how to read its timestamps. Anything
else -- a date with no time, or text that is not a timestamp -- is still rejected.

The generated modules import `Timestamp` from here; `codegen/python/postprocess.py`
(`fix_naive_timestamps`) does the swap.
"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BeforeValidator


def _require_time_part(value: Any) -> Any:
    """Reject a bare date: pydantic reads `2024-01-01` as midnight, which is neither
    an RFC 3339 timestamp nor something the other two packages accept."""
    if isinstance(value, str) and "T" not in value.upper():
        raise ValueError(f"{value!r} is not a timestamp: expected a date and a time")
    return value


Timestamp = Annotated[datetime, BeforeValidator(_require_time_part)]
"""A timestamp with or without an offset, kept as written."""

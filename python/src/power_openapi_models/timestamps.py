"""Hand-written (NOT generated): the types the generated models use for
`format: date-time` and `format: date-time-local` fields.

datamodel-codegen emits pydantic's `AwareDatetime` and `NaiveDatetime`. They accept more
than RFC 3339: a space or a lowercase `t` as the separator, no seconds, six fractional
digits, an offset without a colon, and (`AwareDatetime` only) an epoch number. They also
write six fractional digits.
The schemas allow only the RFC 3339 forms, with at most three fractional digits. These
types check a string against the same forms as the schema `pattern`, and write at most
milliseconds. A `datetime` object is accepted when it has no sub-millisecond part.

The generated modules import these types from here; `codegen/python/postprocess.py`
(`fix_rfc3339_timestamps`) does the swap.
"""

import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, TypeAlias

from pydantic import AfterValidator, BeforeValidator, PlainSerializer

_CLOCK = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?"
_OFFSET = re.compile(_CLOCK + r"(Z|[+-]\d{2}:\d{2})", re.ASCII)
_LOCAL = re.compile(_CLOCK, re.ASCII)


def _checked(form: str, pattern: re.Pattern[str]) -> Callable[[Any], Any]:
    def check(value: Any) -> Any:
        if isinstance(value, str):
            if pattern.fullmatch(value) is None:
                raise ValueError(f"{value!r} is not an RFC 3339 {form}")
            return value
        if isinstance(value, datetime):
            if value.microsecond % 1000:
                raise ValueError(f"{value!r} has a sub-millisecond part")
            return value
        raise ValueError(f"expected an RFC 3339 {form} string, got {type(value).__name__}")

    return check


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError(f"{value!r} has no time zone; a date-time needs one")
    return value


def _naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        raise ValueError(f"{value!r} has a time zone; a date-time-local has none")
    return value


def _written(value: datetime) -> str:
    text = value.isoformat(timespec="seconds")
    if value.microsecond:
        text = value.isoformat(timespec="milliseconds")
    if text.endswith("+00:00"):
        return text[: -len("+00:00")] + "Z"
    return text


OffsetDatetime: TypeAlias = Annotated[
    datetime,
    BeforeValidator(_checked("date-time", _OFFSET)),
    AfterValidator(_aware),
    PlainSerializer(_written, when_used="json"),
]
"""An RFC 3339 `date-time`: a timestamp with `Z` or a UTC offset."""

LocalDatetime: TypeAlias = Annotated[
    datetime,
    BeforeValidator(_checked("date-time-local", _LOCAL)),
    AfterValidator(_naive),
    PlainSerializer(_written, when_used="json"),
]
"""An RFC 3339 `date-time-local`: a timestamp with no offset, a wall clock."""

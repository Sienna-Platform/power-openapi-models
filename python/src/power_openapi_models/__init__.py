"""Typed Python models for the Sienna power system data format.

Generated from SiennaSchemas. See `__schema_version__` for the schema release
these models were built from.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from pathlib import Path

from power_openapi_models import (
    core,
    document,
    dynamics,
    infrastructure_core,
    investments,
    operations,
    timeseries,
)

try:
    __version__ = _version("power-openapi-models")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0.dev0"


def _read_schema_version() -> str:
    """The SiennaSchemas release these models were generated from.

    Shipped as package data so it is answerable at runtime -- the first
    question worth asking about a generated model is which schema produced it.
    """
    marker = Path(__file__).parent / "_schema_version.txt"
    try:
        return marker.read_text().strip()
    except OSError:
        return "unknown"


__schema_version__ = _read_schema_version()

__all__ = [
    "core",
    "document",
    "dynamics",
    "infrastructure_core",
    "investments",
    "operations",
    "timeseries",
    "__version__",
    "__schema_version__",
]

"""Hand-written (NOT generated): the SystemDocument and PortfolioDocument containers
and their JSON I/O.

Counterpart of `PowerOpenAPIModels.jl/src/system_document.jl` and
`portfolio_document.jl`.
`Core/SystemDocument.json` and `Investments/PortfolioDocument.json` in SiennaSchemas are
authoritative for the two shapes; this module mirrors their properties and `required`
lists field for field.

Both are hand-written for the same reason the schemas record: `components` is a map from
type name to an array of heterogeneous objects, which the generator cannot express as
typed buckets, so it skips the whole document type.

There is no document-level `unit_system` or `base_power`: every value is interpretable
from its own component blob alone, via that blob's own basis-selector property
(`power_units`, `parameter_units`, ...) and, for a COMPONENT_BASE reading, that blob's
own `base_power`. `SystemDocument` forbids both fields outright.

`components` and `supplemental_attributes` stay untyped (`dict`/`list[dict]`): they hold
heterogeneous objects keyed or discriminated by a type name this package cannot enumerate
statically.

The other six association arrays (`supplemental_attribute_associations`,
`plant_associations`, `combined_cycle_associations`, `service_associations`,
`trading_hub_associations`, `voltage_control_associations`) and
`time_series_associations` all have generated
classes (`infrastructure_core.models.SupplementalAttributeAssociation`,
`operations.models.{PlantAssociation, CombinedCycleAssociation,
ServiceAssociation, TradingHubAssociation, VoltageControlAssociation}`,
`timeseries.models.TimeSeriesAssociation`), so those fields are typed with
them — imported defensively, so this module still degrades to `list[dict]`
rather than failing to import if a future regeneration ever drops one of
these again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, RootModel

from power_openapi_models._versioning import (
    BUNDLE_DIR,
    READER_VERSION,
    SchemaVersionError,
    check_schema_version,
    validate_source,
)
from power_openapi_models._versioning import _check as _check_version

try:
    from power_openapi_models.infrastructure_core.models import (
        SupplementalAttributeAssociation,
    )
except ImportError:
    SupplementalAttributeAssociation = dict

try:
    from power_openapi_models.operations.models import (
        CombinedCycleAssociation,
        PlantAssociation,
        ServiceAssociation,
        TradingHubAssociation,
        VoltageControlAssociation,
    )
except ImportError:
    CombinedCycleAssociation = PlantAssociation = ServiceAssociation = dict
    TradingHubAssociation = VoltageControlAssociation = dict

try:
    from power_openapi_models.timeseries.models import TimeSeriesAssociation
except ImportError:
    TimeSeriesAssociation = dict

try:
    from power_openapi_models.investments.models import (
        PortfolioFinancialData,
        RequirementAssociation,
    )
except ImportError:
    PortfolioFinancialData = RequirementAssociation = dict


__all__ = [
    "PortfolioDocument",
    "SchemaVersionError",
    "SystemDocument",
    "check_schema_version",
    "get_source_schema_version",
    "read_document",
    "read_portfolio_document",
    "upgrade_document",
    "upgrade_portfolio_document",
    "write_document",
    "write_portfolio_document",
]

SCHEMA_VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?$"


class _StampedDocument(BaseModel):
    """What both documents share: the `schema_version` stamp and the version the
    container was read at.

    `schema_version` is required in the file. A document built in code defaults it to
    this package's version, and a reader never relies on that default:
    `check_schema_version` runs on the raw JSON first. The writer stamps its own
    choice (see `write_document`), so the field's value is only ever the version the
    document had when it was read or built.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default_factory=lambda: READER_VERSION,
        pattern=SCHEMA_VERSION_PATTERN,
        description="Version of the schema release that wrote this document, without a "
        "leading `v`.",
    )

    # Not serialized, like `counter` in the Julia container: the stamp on disk is the only
    # persisted version.
    _source_schema_version: str = PrivateAttr(default="")

    def model_post_init(self, __context: object) -> None:
        self._source_schema_version = self.schema_version


def get_source_schema_version(doc: _StampedDocument) -> str:
    """The schema version `doc` was read at, or this package's version for a new document."""
    return doc._source_schema_version


class SystemDocument(_StampedDocument):
    """A whole serialized power system: components bucketed by type name, the
    association tables linking them, and the name of the HDF5 sidecar holding time
    series values. Mirrors `Core/SystemDocument.json`.
    """

    name: str | None = Field(None, description="Optional system name.")
    description: str | None = Field(
        None, description="Optional free-text description of the system."
    )
    frequency: float | None = Field(None, gt=0, description="Nominal system frequency. Units: Hz.")
    components: dict[str, list[dict]] = Field(
        ...,
        description="Components grouped by type name, e.g. "
        '`{"ACBus": [...], "ThermalStandard": [...]}`. Keys are the referenced '
        "schema's `title` and must be emitted in sorted order.",
    )
    supplemental_attributes: list[dict] = Field(
        ...,
        description="Supplemental attributes in one flat array rather than bucketed "
        "by type; `supplemental_attribute_associations` carries the `attribute_type` "
        "discriminator a consumer needs to pick a converter.",
    )
    supplemental_attribute_associations: list[SupplementalAttributeAssociation] = Field(
        ...,
        description="Links each plain supplemental attribute to the entity it "
        "describes. One row per (attribute, entity) pair.",
    )
    plant_associations: list[PlantAssociation] = Field(
        ...,
        description="Links a power plant supplemental attribute to a generating "
        "unit and the group it belongs to within the plant.",
    )
    combined_cycle_associations: list[CombinedCycleAssociation] = Field(
        ...,
        description="Links a CombinedCycleBlock plant to a CT or CA unit and the "
        "HRSG it feeds into or receives from.",
    )
    service_associations: list[ServiceAssociation] = Field(
        ...,
        description="Links a service to one component that contributes to it. "
        "One row per (service, member) pair.",
    )
    trading_hub_associations: list[TradingHubAssociation] = Field(
        default_factory=list,
        description="Links a trading hub to one associated entity. Added after the "
        "other association arrays, so older documents omit it.",
    )
    voltage_control_associations: list[VoltageControlAssociation] = Field(
        default_factory=list,
        description="Links a voltage control group to one member device. Added after "
        "the other association arrays, so older documents omit it.",
    )
    time_series_associations: list[TimeSeriesAssociation] = Field(
        ...,
        description="Time series metadata rows, one per (series, owner) "
        "association. Values themselves never appear here.",
    )
    ext: dict[str, dict] = Field(
        default_factory=dict,
        description="Source data no schema field claims, keyed by the stringified "
        "component id it belongs to.",
    )
    time_series_storage_file: str | None = Field(
        ...,
        description="Basename of the HDF5 sidecar holding time series values, or "
        "null when the system has no time series.",
    )


_D = TypeVar("_D", bound=_StampedDocument)


def _read(cls: type[_D], path: str | Path, *, reader: str = READER_VERSION) -> _D:
    """The one read path: check the stamp on the raw JSON, then decode.

    Checking before `model_validate` is what lets a newer document report its version
    instead of tripping `extra="forbid"` on a key this reader does not know.
    """
    raw = json.loads(Path(path).read_text())
    _check_version(raw, reader)
    return cls.model_validate(raw)


def read_document(path: str | Path) -> SystemDocument:
    """Read a `SystemDocument` from a JSON file.

    Raises `SchemaVersionError` unless the document's `schema_version` is the reader's
    or an older one on the same compatibility line.
    """
    return _read(SystemDocument, path)


def _prune(value: object, dumped: object) -> None:
    """Drop explicit nulls of optional properties from `dumped`, the JSON dump of `value`.

    One level of rows is as far as this reaches: the generated models cannot say which
    nested field equals its schema default without per-field generator support, and
    `components` rows are untyped dicts that the writer emits as given.
    """
    if isinstance(value, list) and isinstance(dumped, list):
        for item, row in zip(value, dumped, strict=True):
            _prune(item, row)
        return
    inner = value.root if isinstance(value, RootModel) else value
    if isinstance(inner, BaseModel) and isinstance(dumped, dict):
        for name, field in type(inner).model_fields.items():
            if not field.is_required() and name in dumped and dumped[name] is None:
                del dumped[name]


_FINANCIAL_RATES = ("discount_rate", "inflation_rate", "interest_rate")


def _encode(doc: _StampedDocument, stamp: str) -> dict:
    """The canonical JSON tree of `doc`, stamped `stamp`.

    Omits an optional property that is absent, null, or equal to its schema default, so
    a document read at an older version and written back carries nothing that version's
    strict schema rejects. `exclude_unset` handles absent; `exclude_none` would instead
    strip required properties that are legitimately null (`time_series_storage_file`),
    so nulls are judged per field.
    """
    dumped = doc.model_dump(mode="json", exclude_unset=True)
    data = {}
    for name, field in type(doc).model_fields.items():
        if name == "schema_version" or name not in dumped:
            continue
        value = dumped[name]
        # `ext` has no schema default: its pydantic factory is not a reason to drop a set `{}`.
        if not field.is_required() and (
            value is None
            or (name != "ext" and value == field.get_default(call_default_factory=True))
        ):
            continue
        _prune(getattr(doc, name), value)
        if name == "financial_data":
            # Required in the schema though the model defaults them: write them always,
            # in field order so a rewrite is byte-stable.
            fd = getattr(doc, name)
            value = {
                k: value[k] if k in value else getattr(fd, k)
                for k in type(fd).model_fields
                if k in value or k in _FINANCIAL_RATES
            }
        data[name] = value
    data["components"] = {key: data["components"][key] for key in sorted(data["components"])}
    # Sort the top level too, not just `components`. Field-declaration order is an
    # artifact of how the model happens to be written; sorting makes the output a
    # function of the data alone, so re-writing a document is a no-op in diff and two
    # producers agree byte for byte. The stamp stays first, as in the schema.
    return {"schema_version": stamp, **{key: data[key] for key in sorted(data)}}


def _write(
    doc: _StampedDocument,
    path: str | Path,
    *,
    indent: int | None,
    bundle_name: str,
    schema_version: Literal["current", "source"] = "current",
    reader: str = READER_VERSION,
    bundle_dir: Path = BUNDLE_DIR,
) -> None:
    """Dump `doc` to `path` as JSON under the rules both document types share.

    `reader` and `bundle_dir` are parameters so tests can stand in a reader and the
    bundles built from a SiennaSchemas checkout.
    """
    if schema_version == "current":
        stamp = reader
    elif schema_version == "source":
        stamp = get_source_schema_version(doc)
        # A source stamp this reader could not itself read is not a stamp to write.
        _check_version({"schema_version": stamp}, reader)
    else:
        raise ValueError(f"schema_version must be 'current' or 'source', got {schema_version!r}")
    data = _encode(doc, stamp)
    if stamp != reader:
        validate_source(data, stamp, bundle_name, bundle_dir)
    # Trailing newline: POSIX text-file convention, and it makes read -> write
    # byte-identical against documents produced by other tools in this ecosystem,
    # which all emit one.
    Path(path).write_text(json.dumps(data, indent=indent) + "\n")


def write_document(
    doc: SystemDocument,
    path: str | Path,
    *,
    indent: int | None = 2,
    schema_version: Literal["current", "source"] = "current",
) -> None:
    """Write `doc` to `path` as JSON, with `components` keys sorted for
    deterministic output — the schema requires the same.

    `schema_version="current"` stamps this package's schema version, so reading and
    writing upgrades a document. `"source"` keeps the version the document was read at
    (`get_source_schema_version`): when that is older, the encoded document is checked
    against that version's strict schema and the write fails, listing every offending
    path, rather than dropping anything. That check needs the `source-version` extra.
    """
    _write(doc, path, indent=indent, bundle_name="SystemDocument", schema_version=schema_version)


def _refuse_overwrite(dst: str | Path, force: bool) -> None:
    if Path(dst).exists() and not force:
        raise FileExistsError(f"{dst} exists; pass force=True to overwrite it")


def upgrade_document(src: str | Path, dst: str | Path, *, force: bool = False) -> None:
    """Read the `SystemDocument` at `src` and write it to `dst` at the current schema version."""
    _refuse_overwrite(dst, force)
    write_document(read_document(src), dst)


class PortfolioDocument(_StampedDocument):
    """A whole serialized investment portfolio: the candidate technologies,
    regional aggregations, and policy requirements that make up an expansion
    problem, the supplemental attributes describing them, the association
    tables linking them, and the names of the sidecar files holding the base
    power system and the time series values. Mirrors
    `Investments/PortfolioDocument.json`.

    There is no document-level unit system or base power. A portfolio records
    every value in natural units and, unlike a power system, carries no
    per-unit basis of its own. The only unit marker that ever appears is an
    embedded cost payload's own `power_units` (on a `CostCurve` or
    `FuelCurve`), which is intrinsic to that curve.

    The base power system is not embedded: `base_system_file` names a sidecar
    holding it as its own `SystemDocument`, so a portfolio and its base system
    can be written, moved, and read together.
    """

    name: str | None = Field(None, description="Optional portfolio name.")
    description: str | None = Field(
        None, description="Optional free-text description of the portfolio."
    )
    data_source: str | None = Field(
        None, description="Optional identifier of the source the portfolio data was drawn from."
    )
    aggregation: str = Field(
        ...,
        description="Qualified type name of the regional aggregation the portfolio "
        "groups its regions by. A type identifier resolved by the consumer, not a "
        "component in the document.",
    )
    financial_data: PortfolioFinancialData | None = Field(
        None,
        description="Portfolio-wide financial parameters: the base economic year every "
        "cost is discounted to a net present value in, and the discount, inflation, and "
        "interest rates used in that conversion. Absent when the portfolio carries no "
        "financial data.",
    )
    components: dict[str, list[dict]] = Field(
        ...,
        description="Components grouped by type name, e.g. "
        '`{"SupplyTechnology": [...], "StorageTechnology": [...]}`. Keys are the '
        "referenced schema's `title` and must be emitted in sorted order.",
    )
    supplemental_attributes: list[dict] = Field(
        ...,
        description="Supplemental attributes in one flat array rather than bucketed by "
        "type; `supplemental_attribute_associations` carries the `attribute_type` "
        "discriminator a consumer needs to pick a converter. Examples: "
        "RetirementPotential, RetrofitPotential, ExistingDevices, TopologyMapping.",
    )
    supplemental_attribute_associations: list[SupplementalAttributeAssociation] = Field(
        ...,
        description="Links each supplemental attribute to the entity it describes. One "
        "row per (attribute, entity) pair.",
    )
    requirements_associations: list[RequirementAssociation] = Field(
        ...,
        description="Links each policy requirement to one member subject to it: "
        "`requirement_id` names the requirement and `entity_id` names the member. One "
        "row per (requirement, member) pair.",
    )
    investment_schedule: dict | None = Field(
        None,
        description="Optional investment decisions container: the schedule of capacity "
        "installations produced by solving the portfolio. A model output rather than an "
        "input, absent from an inputs-only portfolio, and carried opaquely.",
    )
    time_series_associations: list[TimeSeriesAssociation] = Field(
        ...,
        description="Time series metadata rows, one per (series, owner) association. "
        "Values themselves never appear here.",
    )
    ext: dict[str, dict] = Field(
        default_factory=dict,
        description="Source data no schema field claims, keyed by the stringified "
        "component id it belongs to.",
    )
    base_system_file: str | None = Field(
        ...,
        description="Basename of the sidecar holding the base power system this "
        "portfolio expands, serialized as its own system document, or null when the "
        "portfolio has no base system.",
    )
    time_series_storage_file: str | None = Field(
        ...,
        description="Basename of the HDF5 sidecar holding time series values, or null "
        "when the portfolio has no time series.",
    )


def read_portfolio_document(path: str | Path) -> PortfolioDocument:
    """Read a `PortfolioDocument` from a JSON file.

    Same version rule as `read_document`.
    """
    return _read(PortfolioDocument, path)


def write_portfolio_document(
    doc: PortfolioDocument,
    path: str | Path,
    *,
    indent: int | None = 2,
    schema_version: Literal["current", "source"] = "current",
) -> None:
    """Write `doc` to `path` as JSON, with `components` keys sorted for
    deterministic output — the schema requires the same.

    Same dump rules and `schema_version` targets as `write_document`.
    """
    _write(doc, path, indent=indent, bundle_name="PortfolioDocument", schema_version=schema_version)


def upgrade_portfolio_document(src: str | Path, dst: str | Path, *, force: bool = False) -> None:
    """Read the `PortfolioDocument` at `src` and write it to `dst` at the current schema version."""
    _refuse_overwrite(dst, force)
    write_portfolio_document(read_portfolio_document(src), dst)

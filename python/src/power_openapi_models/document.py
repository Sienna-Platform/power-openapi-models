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

The other five association arrays (`supplemental_attribute_associations`,
`plant_associations`, `combined_cycle_associations`, `service_associations`,
`trading_hub_associations`) and `time_series_associations` all have generated
classes (`infrastructure_core.models.SupplementalAttributeAssociation`,
`operations.models.{PlantAssociation, CombinedCycleAssociation,
ServiceAssociation, TradingHubAssociation}`,
`timeseries.models.TimeSeriesAssociation`), so those fields are typed with
them — imported defensively, so this module still degrades to `list[dict]`
rather than failing to import if a future regeneration ever drops one of
these again.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

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
    )
except ImportError:
    CombinedCycleAssociation = PlantAssociation = ServiceAssociation = TradingHubAssociation = dict

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


class SystemDocument(BaseModel):
    """A whole serialized power system: components bucketed by type name, the
    association tables linking them, and the name of the HDF5 sidecar holding time
    series values. Mirrors `Core/SystemDocument.json`.
    """

    model_config = ConfigDict(extra="forbid")

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


def read_document(path: str | Path) -> SystemDocument:
    """Read a `SystemDocument` from a JSON file."""
    return SystemDocument.model_validate_json(Path(path).read_text())


def _write(doc: BaseModel, path: str | Path, *, indent: int | None) -> None:
    """Dump `doc` to `path` as JSON under the rules both document types share.

    `exclude_unset=True` keeps an omitted field omitted. Without it
    `model_dump` materializes optional fields (`name`, `description`,
    `frequency`) as explicit `null`s, so reading a document and writing it
    straight back added keys it never had — and put Python at odds with the
    Julia package, whose `_encode` skips absent fields.

    `exclude_unset`, not `exclude_none`: `time_series_storage_file` is
    *required* and is legitimately `null` in real documents, so dropping every
    None would strip a required key and produce a document that no longer
    validates. What should be omitted is what the input never carried, which is
    what `model_fields_set` records.
    """
    data = doc.model_dump(mode="json", exclude_unset=True)
    data["components"] = {key: data["components"][key] for key in sorted(data["components"])}
    # Sort the top level too, not just `components`. Field-declaration order is
    # an artifact of how the model happens to be written; sorting makes the
    # output a function of the data alone, so re-writing a document is a no-op
    # in diff and two producers agree byte for byte.
    data = {key: data[key] for key in sorted(data)}
    # Trailing newline: POSIX text-file convention, and it makes read -> write
    # byte-identical against documents produced by other tools in this
    # ecosystem, which all emit one.
    Path(path).write_text(json.dumps(data, indent=indent) + "\n")


def write_document(doc: SystemDocument, path: str | Path, *, indent: int | None = 2) -> None:
    """Write `doc` to `path` as JSON, with `components` keys sorted for
    deterministic output — the schema requires the same.
    """
    _write(doc, path, indent=indent)


class PortfolioDocument(BaseModel):
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

    model_config = ConfigDict(extra="forbid")

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
    """Read a `PortfolioDocument` from a JSON file."""
    return PortfolioDocument.model_validate_json(Path(path).read_text())


def write_portfolio_document(
    doc: PortfolioDocument, path: str | Path, *, indent: int | None = 2
) -> None:
    """Write `doc` to `path` as JSON, with `components` keys sorted for
    deterministic output — the schema requires the same.

    Same dump rules as `write_document`, for the same reasons: `exclude_unset`
    to keep an omitted field omitted rather than materializing it as an
    explicit `null`, a sorted top level so output is a function of the data
    alone, and a trailing newline.
    """
    _write(doc, path, indent=indent)

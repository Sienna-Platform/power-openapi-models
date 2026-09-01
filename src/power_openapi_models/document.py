"""Hand-written (NOT generated): the SystemDocument container and its JSON I/O.

Counterpart of `PowerOpenAPIModels.jl/src/document.jl`. `Core/SystemDocument.json` in
SiennaSchemas is authoritative for the shape; this module mirrors its properties and
`required` list field for field.

There is no document-level `unit_system` or `base_power`: every value is interpretable
from its own component blob alone, via that blob's own basis-selector property
(`power_units`, `parameter_units`, ...) and, for a COMPONENT_BASE reading, that blob's
own `base_power`. `SystemDocument` forbids both fields outright.

`components` and `supplemental_attributes` stay untyped (`dict`/`list[dict]`): they hold
heterogeneous objects keyed or discriminated by a type name this package cannot enumerate
statically.

The other five association arrays (`supplemental_attribute_associations`,
`plant_associations`, `combined_cycle_associations`, `service_associations`,
`trading_hub_associations`) and `time_series_associations` all have generated classes
(`core.models.SupplementalAttributeAssociation`, `operations.models.{PlantAssociation,
CombinedCycleAssociation,ServiceAssociation,TradingHubAssociation}`,
`timeseries.models.TimeSeriesAssociation`), so those fields are typed with them — imported
defensively, so this module still degrades to `list[dict]` rather than failing to import
if a future regeneration ever drops one of these again.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

try:
    from power_openapi_models.core.models import SupplementalAttributeAssociation
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
    CombinedCycleAssociation = PlantAssociation = ServiceAssociation = (
        TradingHubAssociation
    ) = dict

try:
    from power_openapi_models.timeseries.models import TimeSeriesAssociation
except ImportError:
    TimeSeriesAssociation = dict


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
    frequency: float | None = Field(
        None, gt=0, description="Nominal system frequency. Units: Hz."
    )
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


def write_document(
    doc: SystemDocument, path: str | Path, *, indent: int | None = 2
) -> None:
    """Write `doc` to `path` as JSON, with `components` keys sorted for
    deterministic output — the schema requires the same.
    """
    data = doc.model_dump(mode="json")
    data["components"] = {
        key: data["components"][key] for key in sorted(data["components"])
    }
    Path(path).write_text(json.dumps(data, indent=indent))

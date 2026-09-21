# power-openapi-models (Python)

[![PyPI](https://img.shields.io/pypi/v/power-openapi-models.svg)](https://pypi.org/project/power-openapi-models/)
[![Python](https://img.shields.io/pypi/pyversions/power-openapi-models.svg)](https://pypi.org/project/power-openapi-models/)
[![CI](https://github.com/Sienna-Platform/power-openapi-models/actions/workflows/test.yml/badge.svg)](https://github.com/Sienna-Platform/power-openapi-models/actions/workflows/test.yml)
[![License](https://img.shields.io/pypi/l/power-openapi-models.svg)](../LICENSE)

Typed Python models for the Sienna power system data format — every
component, association, and time series row as a validated pydantic v2
model.

> [!WARNING]
> **Pre-release.** Every version below `1.0` can change incompatibly in any
> release; no stability is promised until `1.0`. Under PEP 440, `0.1.0` is
> not itself a "pre-release" version, so `pip install power-openapi-models`
> installs it with no `--pre` flag and no warning. Pin an exact version.

## Install

```bash
pip install power-openapi-models
```

```bash
uv add power-openapi-models
```

## Quickstart

```python
from power_openapi_models.core.models import ACBus, ACBusType

bus = ACBus(
    id=1,
    name="bus-1",
    available=True,
    number=1,
    bustype=ACBusType.PV,
    base_voltage=230.0,
)
print(bus.name, bus.bustype, bus.base_voltage)
print(bus.model_dump_json(exclude_none=True))
```

## The modules

| Module | Holds | Reach for it when |
|---|---|---|
| `infrastructure_core` | Units (`UnitSystem`), function data, shared value shapes (`MinMax`, `UpDown`, ...) | You need a domain-neutral building block used across every other module |
| `core` | Power enums, curves, costs, buses | You are working with shared power types or need `ACBus`/`DCBus` |
| `operations` | Topology, branches, injections, services, market | You are working with the grid itself |
| `investments` | Technologies, financials, requirements, regions | You are doing capacity expansion |
| `dynamics` | Dynamic generator and inverter components | You are doing transient stability |
| `timeseries` | The six time series association types | You are handling forecasts or profiles |
| `document` | `SystemDocument`, the hand-written envelope, plus `read_document`/`write_document` | You are loading or saving a whole serialized system |

Import a class from its module's `.models` submodule:
`from power_openapi_models.core.models import ACBus`.

## Concepts worth knowing before you start

### Unit systems

Many component fields carry a sibling `*_units` field (for example
`ThermalStandard.power_units`) that says how to read every other power-family
field on that same component. There is no document-level unit system: each
component blob is self-describing.

```python
from power_openapi_models.infrastructure_core.models import UnitSystem

print(list(UnitSystem))
print(UnitSystem.NATURAL_UNITS.value)
```

`NATURAL_UNITS` means values are in physical units — MW, MVAr, kV, ohm.
`COMPONENT_BASE` means per-unit against the component's own recorded
`base_power`. Getting this wrong is the most common source of
wrong-by-a-factor-of-100 bugs across the ecosystem.

### Discriminated unions carry a `.root`

Several types are one of several shapes, chosen by a discriminator field.
They are pydantic `RootModel`s, and the concrete variant is reached through
`.root`.

```python
from power_openapi_models.infrastructure_core.models import (
    FunctionData,
    LinearFunctionData,
)

parsed = FunctionData.model_validate(
    {"function_type": "LINEAR", "proportional_term": 2.0, "constant_term": 5.0}
)
assert isinstance(parsed.root, LinearFunctionData)
print(parsed.root.proportional_term)
```

> [!IMPORTANT]
> **This differs from the TypeScript package**, where the same types are zod
> unions and `parse` returns the variant directly, with no `.root`. Porting
> code between the two languages, this is the first thing that breaks.

### Components reference each other by integer id

There are no object references on the wire. `ThermalStandard.bus`, for
example, names its bus by id, and resolving it is the reader's job.

```python
from power_openapi_models.core.models import ACBus

buses = [
    ACBus(id=1, name="a", available=True, number=1, base_voltage=230.0),
    ACBus(id=2, name="b", available=True, number=2, base_voltage=230.0),
]
by_id = {bus.id: bus for bus in buses}
print(by_id[2].name)
```

### The document envelope

A serialized system is one object: `components` keyed by type name, a flat
`supplemental_attributes` array, several association arrays, and
`time_series_storage_file` naming a sidecar. There is no document-level
`unit_system` or `base_power` — `SystemDocument` forbids both fields
outright, since every component already carries its own basis.

**Time series values never appear in the document.**
`time_series_associations` carries only the metadata rows; the values live
in the sidecar named by `time_series_storage_file`, and reading it is the
consumer's job.

## Round-tripping

`read_document` followed by `write_document` reproduces the input byte for
byte. Fields the input never carried stay omitted rather than being written
back as explicit nulls, top-level keys are sorted, and the file ends with a
newline.

## Worked example

```python
from power_openapi_models.document import read_document

doc = read_document("../fixtures/case14_operations.NATURAL_UNITS.json")

buses = doc.components["ACBus"]
generators = doc.components["ThermalStandard"]
print(f"{len(buses)} buses, {len(generators)} thermal generators")

gen = generators[0]
limits = gen["active_power_limits"]
print(gen["name"], "active power limits (MW):", limits["min"], "-", limits["max"])
```

## Validation

Bad data raises `pydantic.ValidationError`, which names the field and the
rule:

```python
from pydantic import ValidationError

from power_openapi_models.infrastructure_core.models import LinearFunctionData

try:
    LinearFunctionData(function_type="NOT_A_TYPE", proportional_term=1.0, constant_term=0.0)
except ValidationError as exc:
    print(exc.error_count(), "error(s)")
    print(exc.errors()[0]["loc"], exc.errors()[0]["type"])
```

## Type checking

The package ships a PEP 561 `py.typed` marker, so mypy and pyright pick the
annotations up with no configuration.

## Versioning and provenance

These models are generated. The schema release they came from is recorded
in the package:

```python
import power_openapi_models

print(power_openapi_models.__version__)
print(power_openapi_models.__schema_version__)
```

Quote `__schema_version__` in bug reports — it identifies the exact schema
release the models were built from.

## Links

- [SiennaSchemas](https://github.com/Sienna-Platform/SiennaSchemas) — the schemas these models are generated from, and where schema bugs belong
- [@sienna-platform/power-openapi-models](../typescript/README.md) — the TypeScript package generated from the same schemas, kept in lockstep by a CI equivalence gate
- [PowerOpenAPIModels.jl](https://github.com/Sienna-Platform/PowerOpenAPIModels) — the Julia packages generated from the same schemas
- [CONTRIBUTING.md](../CONTRIBUTING.md) — regenerating, and why you must not edit the models by hand
- [CHANGELOG.md](../CHANGELOG.md)

## License

BSD 3-Clause. See [LICENSE](../LICENSE).

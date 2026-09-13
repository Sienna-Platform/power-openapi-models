# power-openapi-models (TypeScript)

[![npm](https://img.shields.io/npm/v/%40sienna-platform%2Fpower-openapi-models.svg)](https://www.npmjs.com/package/@sienna-platform/power-openapi-models)
[![CI](https://github.com/Sienna-Platform/power-openapi-models/actions/workflows/test.yml/badge.svg)](https://github.com/Sienna-Platform/power-openapi-models/actions/workflows/test.yml)
[![License](https://img.shields.io/npm/l/%40sienna-platform%2Fpower-openapi-models.svg)](../LICENSE)

Typed TypeScript models for the Sienna power system data format — every
component, association, and time series row as a validated [zod](https://zod.dev)
schema.

> [!WARNING]
> **Pre-release.** Every version below `1.0` can change incompatibly in any
> release; no stability is promised until `1.0`. Pin an exact version.

## Install

```bash
npm install @sienna-platform/power-openapi-models zod
```

`zod` is a peer dependency (`^4`), not a transitive one, so a consumer never
ends up with two copies of it.

Requires **Node.js >=22**: `readDocument`/`writeDocument` depend on
`JSON.rawJSON` and `JSON.parse`'s reviver `context` argument.

## Quickstart

```ts
import { ACBus, ACBusType } from "@sienna-platform/power-openapi-models/core";

const bus = ACBus.parse({
  id: 1,
  name: "bus-1",
  available: true,
  number: 1,
  bustype: ACBusType.enum.PV,
  base_voltage: 230.0,
});
console.log(bus.name, bus.bustype, bus.base_voltage);
```

Bad data throws a `ZodError` naming the field and the rule:

```ts
import { ACBus } from "@sienna-platform/power-openapi-models/core";

try {
  ACBus.parse({ id: 1, name: "bus-1", available: true, number: 1, bustype: "NOT_A_TYPE" });
} catch (err) {
  console.log(err.issues[0].path, err.issues[0].code);
}
```

## The subpaths

| Import from | Holds | Reach for it when |
|---|---|---|
| `@sienna-platform/power-openapi-models` | Every domain, namespaced (`core.ACBus`, `document.SystemDocument`, ...) | You want one import instead of several |
| `.../infrastructure_core` | Units (`UnitSystem`), function data, shared value shapes (`MinMax`, `UpDown`, ...) | You need a domain-neutral building block used across every other module |
| `.../core` | Power enums, curves, costs, buses | You are working with shared power types or need `ACBus`/`DCBus` |
| `.../operations` | Topology, branches, injections, services, market | You are working with the grid itself |
| `.../investments` | Technologies, financials, requirements, regions | You are doing capacity expansion |
| `.../dynamics` | Dynamic generator and inverter components | You are doing transient stability |
| `.../timeseries` | The six time series association types | You are handling forecasts or profiles |
| `.../document` | `SystemDocument`, the hand-written envelope, plus `readDocument`/`writeDocument` | You are loading or saving a whole serialized system |

## Concepts worth knowing before you start

### Unit systems

Many component fields carry a sibling `*_units` field (for example
`ThermalStandard.power_units`) that says how to read every other
power-family field on that same component. There is no document-level unit
system: each component blob is self-describing.

### The document envelope

A serialized system is one object: `components` keyed by type name, a flat
`supplemental_attributes` array, several association arrays, and
`time_series_storage_file` naming a sidecar. There is no document-level
`unit_system` or `base_power` — `SystemDocument` forbids both fields
outright, since every component already carries its own basis.

```ts
import { readDocument } from "@sienna-platform/power-openapi-models/document";

const doc = readDocument("../fixtures/case14_operations.NATURAL_UNITS.json");
const buses = doc.components["ACBus"];
console.log(`${buses.length} buses`);
```

**Time series values never appear in the document.**
`time_series_associations` carries only the metadata rows; the values live
in the sidecar named by `time_series_storage_file`.

## Known limitations

**`ext`'s key order is not preserved across a `readDocument` /
`writeDocument` round trip.** `ext` is keyed by a stringified component id
(e.g. `"38"`, `"106"`), and ECMAScript objects unconditionally enumerate any
integer-index-like own property key in ascending *numeric* order ahead of
every other string key — in every engine, regardless of insertion order or
how the object was built. The upstream fixtures write `ext` in ascending
*lexicographic* order (`"106" < "112" < "119" < "38"` as strings), which a
JavaScript object cannot reproduce; there is no JSON API that recovers or
preserves the original order once the data exists as a plain object.

This is semantically inert — JSON object keys are unordered per
[RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) — and it affects `ext`
only: every other field, including every number's exact literal formatting
(`138.0` stays `138.0`, not `138`), round-trips byte-identically. Python's
`write_document` preserves `ext`'s original order (Python dicts don't
reorder integer-like keys), so the Python and TypeScript writers agree on
every field except this one.

## Type checking

Every export is a zod schema; `zod.input<typeof X>` and `zod.output<typeof
X>` give the pre- and post-parse TypeScript types.

## Versioning and provenance

These models are generated from the same OpenAPI schemas as the Python and
Julia packages. See [`.schema-version`](../.schema-version) at the repo root
for the exact SiennaSchemas release.

## Links

- [SiennaSchemas](https://github.com/Sienna-Platform/SiennaSchemas) — the schemas these models are generated from, and where schema bugs belong
- [power-openapi-models (Python)](../python/README.md) — the Python package generated from the same schemas
- [PowerOpenAPIModels.jl](https://github.com/Sienna-Platform/PowerOpenAPIModels) — the Julia packages generated from the same schemas
- [CONTRIBUTING.md](../CONTRIBUTING.md) — regenerating, and why you must not edit the models by hand
- [CHANGELOG.md](../CHANGELOG.md)

## License

BSD 3-Clause. See [LICENSE](../LICENSE).

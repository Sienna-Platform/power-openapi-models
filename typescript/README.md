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

Bad data is rejected, naming the field and the rule. `safeParse` returns
a result rather than throwing; `parse` throws a `ZodError` instead:

```ts
import { ACBus } from "@sienna-platform/power-openapi-models/core";

const result = ACBus.safeParse({
  id: 1,
  name: "bus-1",
  available: true,
  number: 1,
  bustype: "NOT_A_TYPE",
});
if (!result.success) {
  console.log(result.error.issues[0].path, result.error.issues[0].code);
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

### Discriminated unions parse to the variant directly

Several types are one of several shapes, chosen by a discriminator field.
`parse` returns the matching variant itself — read its fields directly.

```ts
import { FunctionData } from "@sienna-platform/power-openapi-models/infrastructure_core";

const parsed = FunctionData.parse({
  function_type: "LINEAR",
  proportional_term: 2.0,
  constant_term: 5.0,
});
console.log(parsed.function_type, parsed.proportional_term);
```

> [!IMPORTANT]
> **This differs from the Python package.** There, the same types are pydantic
> `RootModel`s and the variant is reached through `.root`
> (`parsed.root.proportional_term`). In TypeScript there is no `.root` — the
> value *is* the variant. Porting code between the two languages, this is the
> first thing that breaks.

### Components reference each other by integer id

There are no object references on the wire. `ThermalStandard.bus`, for
example, names its bus by id, and resolving it is the reader's job.

```ts
import { ACBus } from "@sienna-platform/power-openapi-models/core";

const buses = [
  ACBus.parse({ id: 1, name: "a", available: true, number: 1, base_voltage: 230.0 }),
  ACBus.parse({ id: 2, name: "b", available: true, number: 2, base_voltage: 230.0 }),
];
const byId = new Map(buses.map((b) => [b.id, b]));
console.log(byId.get(2)?.name);
```

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

## Worked example

```ts
import { readDocument } from "@sienna-platform/power-openapi-models/document";

const doc = readDocument("../fixtures/case14_operations.NATURAL_UNITS.json");

const buses = doc.components["ACBus"];
const generators = doc.components["ThermalStandard"];
console.log(`${buses.length} buses, ${generators.length} thermal generators`);

const gen = generators[0];
console.log(gen.name, "active power limits (MW):", gen.active_power_limits.min, "-", gen.active_power_limits.max);
```

## Validation

Bad data is rejected with issues naming the field and the rule:

```ts
import { LinearFunctionData } from "@sienna-platform/power-openapi-models/infrastructure_core";

const result = LinearFunctionData.safeParse({
  function_type: "NOT_A_TYPE",
  proportional_term: 1.0,
  constant_term: 0.0,
});
if (!result.success) {
  console.log(result.error.issues.length, "issue(s)");
  console.log(result.error.issues[0].path, result.error.issues[0].code);
}
```

This is the reason the package ships zod schemas rather than bare TypeScript
types: a malformed document fails loudly here, the way it does in Python.
Types alone would erase at build time and let bad data through as a
wrongly-shaped object.

## Round-tripping

`readDocument` followed by `writeDocument` reproduces the input byte for
byte, including each number's exact literal formatting (`138.0` stays
`138.0`, not `138`) — with the single documented exception below.

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

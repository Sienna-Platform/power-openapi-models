# power-openapi-models (Rust)

Typed [`serde`](https://serde.rs) models for the Sienna power system data
format — every component, association, and time series row — generated from
the same SiennaSchemas release as the
[Python](https://pypi.org/project/power-openapi-models/) and
[TypeScript](https://www.npmjs.com/package/@sienna-platform/power-openapi-models)
packages. All three ship in lockstep: one version, one `v*` tag.

**What this is not:** a power-flow solver, an optimization framework, or a
simulation engine. These models carry no numerics; they are the input format,
not the tool.

## Install

```sh
cargo add power-openapi-models
```

The crate reports the schema release it was generated from:

```rust
assert!(power_openapi_models::SCHEMA_VERSION.starts_with('v'));
println!(
    "power-openapi-models {} / SiennaSchemas {}",
    power_openapi_models::VERSION,
    power_openapi_models::SCHEMA_VERSION,
);
```

## Quickstart

A system document holds components bucketed by type name. `components` stays
untyped JSON, because a bucket's type is only known from its key; convert an
entry to its generated type to work with it.

```rust
use power_openapi_models::document::{document_to_string, parse_document};
use power_openapi_models::generated::ACBus;
use serde_json::{json, Value};

let text = json!({
    "schema_version": power_openapi_models::schema_version::current_schema_version(),
    "components": {
        "ACBus": [{
            "id": 3, "number": 101, "name": "BUS 101", "available": true,
            "bustype": "REF", "base_voltage": 138.0
        }]
    },
    "supplemental_attributes": [],
    "supplemental_attribute_associations": [],
    "plant_associations": [],
    "combined_cycle_associations": [],
    "service_associations": [],
    "time_series_associations": [],
    "time_series_storage_file": null
})
.to_string();

let doc = parse_document(&text)?;
let bus: ACBus = serde_json::from_value(Value::Object(doc.components["ACBus"][0].clone()))?;
assert_eq!(bus.name, "BUS 101");
assert_eq!(bus.base_voltage, Some(138.0));

// Reading then writing reproduces a document in canonical form byte for byte.
let written = document_to_string(&doc)?;
assert_eq!(parse_document(&written)?, doc);
# Ok::<(), Box<dyn std::error::Error>>(())
```

Read and write files with `read_document` / `write_document`. `PortfolioDocument`
has the same set: `read_portfolio_document`, `write_portfolio_document`.

## Schema versions

Every document carries `schema_version`. A read compares it with this crate's
(`schema_version::current_schema_version()`) on the raw JSON, before decoding, and
fails with `DocumentError::Version` unless the document is `current` or
`upgradable` (written by an older release of the same compatibility line). The
rule is `schema_version::check_schema_version`.

Writes stamp this crate's version. To keep the version a document was read at,
pass `SchemaVersionTarget::Source`:

```rust,no_run
use power_openapi_models::document::{read_document, write_document, SchemaVersionTarget};

let doc = read_document("system.json")?;
println!("read at schema {}", doc.get_source_schema_version());
write_document(&doc, "out.json", SchemaVersionTarget::Source)?;
# Ok::<(), Box<dyn std::error::Error>>(())
```

For a document read at an older version, a source write checks the encoded
document against that version's strict bundle in `bundles/<version>/` and lists
every path it holds that the older schema does not know; nothing is dropped. It
needs the `source-version` cargo feature and fails without it.
`write_document_with_bundles` takes the bundle directory explicitly. `upgrade_document`
and `upgrade_portfolio_document` read a file and rewrite it at the current version.

## Layout

| Module | Contents |
|---|---|
| `infrastructure_core`, `core`, `operations`, `investments`, `dynamics`, `timeseries` | The types of one SiennaSchemas spec, as the other packages' domain modules. |
| `generated` | Every generated type, including the enums generated for inline schemas. |
| `document` | `SystemDocument`, `PortfolioDocument`, and their JSON I/O. Hand-written. |

Type names are the schema titles verbatim (`ACBus`, `AGC`), with two exceptions
that are not valid Rust type names: `FromTo_ToFrom` is `FromToToFrom` and
`XY_Coords` is `XYCoords`. Field names are the schema's property names in
snake case; where a property is not (`K_d`), `#[serde(rename)]` keeps the wire key.

## Behaviour worth knowing

**Schema defaults are applied.** An omitted field that the schema defaults takes
that default, as in the Python and TypeScript packages, and serializing writes it
out. A required field with a default may be omitted too.

```rust
use power_openapi_models::generated::CostCurve;
use serde_json::json;

let curve: CostCurve = serde_json::from_value(json!({
    "value_curve": {
        "curve_type": "INPUT_OUTPUT",
        "function_data": {
            "function_type": "LINEAR", "constant_term": 0.0, "proportional_term": 1.0
        }
    }
}))?;
assert_eq!(serde_json::to_value(&curve)?["power_units"], "NATURAL_UNITS");
# Ok::<(), Box<dyn std::error::Error>>(())
```

Because serde cannot tell an omitted defaulted field from an explicit one, a typed
value writes its defaults out. `SystemDocument` avoids the consequence: its own
optional fields (`trading_hub_associations`, `ext`) are `Option`s, so `None` means
"the input did not carry it" and stays omitted.

**Enums reject unlisted values**, including the integer ones (`curve_style`
accepts `0` and `1`, nothing else).

**Timestamps may omit the offset.** The schema says RFC 3339, which requires one, but
producers write `2024-01-01T00:00:00`, so all three packages accept it and read it
as UTC. An offset is honoured and the value normalized to UTC; a bare date or text
that is not a timestamp is rejected. Values are always written with a `Z`.

```rust
use power_openapi_models::timestamp::parse;

assert_eq!(parse("2024-01-01T00:00:00")?, parse("2024-01-01T02:00:00+02:00")?);
assert!(parse("2024-01-01").is_err());
# Ok::<(), String>(())
```

**String-keyed maps** (`MinMaxByKey`, `TimeSeriesFeatures`, …) are structs
holding a flattened `additional_properties` map.

**Floats round-trip exactly.** `serde_json`'s default parser can land one ULP off;
this crate enables `float_roundtrip` so a value written is the value read.

**Documents follow the Python package's write rules.** Top-level keys and
`components` keys are sorted, everything else keeps input order, the file ends in
a newline, and unknown keys are rejected. A `frequency` must be positive, and
`time_series_storage_file` (and `base_system_file` on a portfolio) must be
present, though it may be `null`.

## Generation

Everything under `src/` except `lib.rs` and `document.rs` is generated. Fixes go
in [`codegen/rust/`](../codegen/rust/), never in the output. See
[CONTRIBUTING.md](../CONTRIBUTING.md).

## License

BSD 3-Clause. See [LICENSE](LICENSE).

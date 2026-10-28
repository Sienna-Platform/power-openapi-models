# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed — Python

- **An enum field's default was a plain value, not the enum member.** pydantic does not
  validate a default, so `interval_alignment`, `prime_mover_type`, `parameter_units` and
  the other defaulted enum fields held `"PERIOD_ENDING"` or `0` where a validated value
  holds `IntervalAlignment.PERIOD_ENDING`, and `model_dump(mode="json")` warned
  `PydanticSerializationUnexpectedValue`. The Makefile passes `--set-default-enum-member`,
  which covers an enum the module defines; `fix_imported_enum_defaults` covers one it
  imports from `core`. A test checks every defaulted enum field of every model.

### Fixed — TypeScript

- **A model with `if`/`then` rules accepted an unknown property.** orval renders a
  validation-only `allOf` as `zod.unknown().and(...).and(zod.strictObject(...))`, and zod
  v4 lets an undeclared key through an intersection with `unknown()`. `SeriesCompensator`,
  `EmissionsData` and the other schemas with rules were affected.
  `dropUnknownIntersections` removes the placeholders; the rules stay in the strict
  bundles that ajv applies.

## [0.3.0] — 2026-10-26

Generated from SiennaSchemas v0.3.0. Schema 0.3.0 starts a new compatibility
line: a reader rejects a document stamped 0.2.x as incompatible. Regenerate such
documents with a current producer. The
[SiennaSchemas changelog](https://github.com/Sienna-Platform/SiennaSchemas/blob/v0.3.0/CHANGELOG.md)
lists every schema change.

### Changed — schema (all three packages)

- `XY_Coords` is renamed to `TwoDimensionalFunctionPoint` (`XYCoords` in Rust before).
- New types: `SeriesCompensator`, `CurrentLossCurve`, `FuelUnit`,
  `IntervalAlignment`.
- `FuelCurve.fuel_units` is required and has no default.
- New fields: `Area.scheduled_net_interchange`, `Area.out_of_area_load_ids`
  (default `[]`), `InterconnectingConverter.rated_dc_voltage` and
  `rated_ac_voltage`, `DataSource.license`, and `interval_alignment` on the time
  series types.
- Seven DC current fields are in kA, not A. An old value still reads, but it is
  1000 times too large.

### Added — Rust

- The `validate` cargo feature and `validate::Validator`: a check of one value
  against one definition of the crate's strict bundle, for example a component
  or a `TimeSeriesAssociation` row. The bundle is compiled in. The check catches
  what the generated types accept, such as reserved feature names and values
  out of bounds. `DocumentError::Schema` reports each failing path.
- The `units` module: the unit and quantity of each annotated field, the
  sibling field that selects a unit or holds a `pu` base, and the unit
  conversion factors. The generator writes it from the SiennaSchemas `x-unit`
  annotations and `Core/units.json`, by the same rules as the Julia `units.jl`.
  One difference: a quantity's default unit has the factor 1.0. `units.json`
  stores the nominal frequency (60.0) as the `to_default` of `Frequency`/`Hz`,
  and the Julia table repeats it as a factor.

### Changed — Rust

- Every generated struct denies unknown properties, except the string-keyed
  maps. Before, serde dropped a property the schema does not list, so a
  misspelled field read without error. The strict bundles and the two document
  types already rejected such a property.

### Changed — Python and TypeScript

- Every generated model rejects an unknown property, as the Rust types do: the
  Python models set `extra="forbid"` (`datamodel-codegen --extra-fields forbid`),
  and the zod objects are `zod.strictObject`. Before, a misspelled field parsed
  without error and its value was lost. Map schemas (`RootModel` in Python,
  `zod.record` in TypeScript) stay open.

### Changed — repository

- `check_cross_language.py` compares whether each type rejects an unknown
  property, so the Python↔TypeScript and Python↔Rust gates fail when one
  language drops a property that another rejects.

## [0.2.0] — 2026-10-05

Generated from SiennaSchemas v0.2.0. The first release of all three packages from
one tag. Before it, the Rust crate 0.1.0 was published by hand on 2026-09-30.

### Changed — schema (all three packages)

- `SystemDocument` and `PortfolioDocument` require `schema_version`. A document
  without a stamp does not read. Regenerate it with a current producer.
- Shared voltage control: `VoltageControlAssociation`, `ReactivePowerSharing` and
  `VoltageDroopControl`. `SystemDocument` has an optional
  `voltage_control_associations` container. Like `trading_hub_associations`, it
  is written only when it has rows.
- The dynamic generator and dynamic inverter component families,
  `OperationalFlowLimit` with an optional `operational_flow_limit` on the branch
  types, and `switching_times` on `ThermalStandard` and `ThermalMultiStart`.
- A field whose unit changed with a mode enum is now one field for each
  quantity. For example, `TransformerCircuit.control_limits` and
  `controlled_quantity_limits` become `*_limits` bands,
  `SwitchedAdmittance.admittance_limits` becomes `voltage_limits`, and
  `TwoTerminalLCCLine.power_mode` becomes `control_mode`.
- HVDC impedance, voltage and voltage-droop fields are in natural units only.
- Removed: `MonitoredLine` (use `Line.operational_flow_limit`),
  `GenericArcImpedance.max_flow`, and `TopologyMapping`.

### Added — Python

- Schema-version stamp on `SystemDocument` and `PortfolioDocument`: readers check
  `schema_version` on the raw JSON before decoding and raise `SchemaVersionError`
  (`check_schema_version`); writers stamp the shipped schema version and encode
  canonically (absent, null and default-valued optional properties omitted).
  `write_document(..., schema_version="source")` keeps an older stamp after
  validating against that version's strict bundle (optional extra
  `source-version`); `upgrade_document` and `upgrade_portfolio_document` re-stamp.
  Strict bundles ship in `power_openapi_models/bundles/`.

### Added — TypeScript

- Schema-version stamp on both documents, with the same reader rule, canonical
  encoding and `upgrade*` functions as Python: `readDocument` throws
  `SchemaVersionError` (`checkSchemaVersion`) before decoding, and
  `writeDocument(..., { schemaVersion: "source" })` validates against that
  version's strict bundle with the optional peer dependency `ajv` (`^8`).
  Strict bundles ship in `bundles/`.

### Added — Rust (`power-openapi-models`, crates.io)

- `serde` types for the same six domains, generated from the same schemas by
  `openapi-to-rust` (pinned exactly), after a bundling step that resolves
  SiennaSchemas' many files into one OpenAPI 3.1 document. No downgrade to 3.0.
- One module per domain plus `generated` (every type, including inline enums),
  `SCHEMA_VERSION` and `VERSION` constants, and a hand-written `document`
  module (`SystemDocument`, `PortfolioDocument`, read/write) that follows the
  Python package's write rules and round-trips the fixtures byte for byte.
- Schema defaults are applied, integer enums reject unlisted values, and
  timestamps use `chrono`; see the timestamp note below.
- The README is the crate documentation, so its examples run as doctests.
- Schema-version stamp on both documents, with the same reader rule, canonical
  encoding and `upgrade_*` functions as Python: reads return
  `DocumentError::Version` before decoding, and
  `SchemaVersionTarget::Source` validates against that version's strict bundle
  (cargo feature `source-version`). Strict bundles ship in `bundles/`.

### Added — repository

- `make sync-bundles` copies the strict bundles and reader-rule vectors from a
  release tarball into the three packages; `make stamp-fixtures` re-stamps the
  root fixtures to the pinned schema version after a regeneration.
- A Python↔Rust equivalence gate in CI. It and the Python↔TypeScript gate both
  block. `check_cross_language.py --no-julia` runs both without the Julia arm,
  which needs a `PowerOpenAPIModels` checkout matching the pinned schema.
- `release-rust.yml`, publishing from the same `v*` tag over crates.io trusted
  publishing, and a Rust regeneration-drift job.
- Release on merge: a SiennaSchemas release opens a PR here that regenerates
  all three packages and bumps the version, and merging a version bump tags
  `vX.Y.Z` and publishes all three packages.

### Changed from the schema

- **`format: date-time` fields accept a timestamp with no offset, in all three
  packages.** The schemas say RFC 3339, which requires an offset, and each generator
  honoured that (`AwareDatetime`, `zod.iso.datetime({ offset: true })`,
  `chrono::DateTime<Utc>`), so `2024-01-01T00:00:00` was rejected. Real producers
  write that form. A missing offset is read as UTC in Python and Rust; zod only
  validates, so TypeScript returns the string as written. An offset is still honoured,
  and a bare date or non-timestamp is still rejected. This is a deliberate leniency
  of the pinned schema, applied once per language (`fix_naive_timestamps`,
  `fixNaiveTimestamps`, `lenient_timestamps`) and worth raising with SiennaSchemas.

### Fixed

- **`openapi-to-rust` had its own version of the 0.1.0 generator defects**, each found by the
  Python↔Rust gate and fixed in `codegen/rust/`, never in the output:
  - it drops schema `default`s: an optional defaulted field decoded to `None`
    where Python gives the default, a required defaulted field was required, and
    where it used `#[serde(default)]` that is Rust's zero, not the schema's
    (`ac_setpoint`, default 1.0, would silently have been 0.0). A type-level
    default on a referenced schema also applies to a required field of that type;
  - it turns an integer `enum` into a bare `i64`, so `curve_style: 5` was
    accepted where Python and TypeScript reject it;
  - it emits struct fields alphabetically, so typed rows wrote keys in a
    different order from the other packages, and it derives `PartialEq` on enums
    but not structs.
  It also needed `serde_json`'s `float_roundtrip`: without it a parsed float can be
  one ULP off, which broke byte-identical round-trips.

## [0.1.0] — 2026-09-29

First release. Two packages, one version, one tag, one schema pin. The Rust
crate 0.1.0 was published by hand on 2026-09-30, from a later commit. The 0.2.0
section lists the Rust SDK.

### Added — Python (`power-openapi-models`, PyPI)

- Typed pydantic v2 models for the Sienna power system data format, generated
  from SiennaSchemas.
- Six generated modules: `infrastructure_core`, `core`, `operations`,
  `investments`, `dynamics`, `timeseries`, plus the hand-written `document`
  module (`SystemDocument`, `read_document`, `write_document`).
- PEP 561 `py.typed` marker; the package ships as fully typed.
- `__version__` and `__schema_version__` for runtime provenance.

### Added — TypeScript (`@sienna-platform/power-openapi-models`, npm)

- zod schemas for the same six domains, generated from the same schemas, with
  `zod.input`/`zod.output` types inferred from them. Runtime validation at
  parity with pydantic, not compile-time types only.
- Subpath exports per domain plus `./document`, dual ESM/CJS with `.d.ts`.
- `zod` is a **peer** dependency (`^4`), so a consumer cannot end up with two
  copies of zod. The generated code uses the zod v4 API.
- Hand-written `document.ts` mirroring `Core/SystemDocument.json`, the
  counterpart of Python's `document.py`.

### Added — repository

- Multi-language layout: `python/`, `typescript/`, and a prepared `rust/`.
  Shared at the root: the `.schema-version` pin, the fixtures both languages
  round-trip, `codegen/`, and the cross-language check.
- `scripts/check_version_sync.py` — a `v*` tag cannot publish one language at a
  version the others do not carry, and with `--require` cannot silently publish
  nothing.
- A Python↔TypeScript equivalence gate in CI.

### Fixed

- **Both generators silently dropped schema defaults, in opposite places.** The
  new Python↔TypeScript gate found 156 field-level disagreements between the two
  packages, every one confirmed against the schema:
  - datamodel-code-generator honours `required` but drops the `default` when a
    property is **both** required and defaulted, so `CostCurve(...)` omitting
    `vom_cost` raised `ValidationError` in Python while the same document loaded
    in TypeScript. Fixed generally for every such property, not case by case;
    this subsumes the former one-off `fix_costcurve_power_units_default`.
  - orval drops a property's `default` outright, so an omitted
    `EmissionsData.mass_unit` was `'KG'` in Python and `undefined` in
    TypeScript. Defaults are now restored from the schema.
  - orval PascalCases all-caps schema titles (`AGC` → `Agc`, `SEXS` → `Sexs`),
    so the two packages exported different identifiers for the same schema.
    TypeScript now uses the schema title verbatim, as Python does.
- `document.write_document` did not round-trip. It materialized `name`,
  `description`, and `frequency` as explicit nulls (adding three keys the input
  never had), emitted top-level keys in field-declaration order, and omitted the
  trailing newline. Reading a document and writing it back is now byte-identical.
- `scripts/check_cross_language.py` had been passing vacuously: it matched
  `Base.@kwdef mutable struct` while the Julia generator emits
  `Base.@kwdef struct`, so it parsed zero structs, compared zero types, and
  reported "Surfaces agree". It now refuses to report agreement when it
  compared nothing, and compares Julia's JSON keys rather than its snake_cased
  struct identifiers.

[0.3.0]: https://github.com/Sienna-Platform/power-openapi-models/releases/tag/v0.3.0
[0.2.0]: https://github.com/Sienna-Platform/power-openapi-models/releases/tag/v0.2.0
[0.1.0]: https://github.com/Sienna-Platform/power-openapi-models/releases/tag/v0.1.0

# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Unreleased

First release. Three packages, one version, one tag, one schema pin.

### Added — Python (`power-openapi-models`, PyPI)

- Typed pydantic v2 models for the Sienna power system data format, generated
  from SiennaSchemas.
- Six generated modules: `infrastructure_core`, `core`, `operations`,
  `investments`, `dynamics`, `timeseries`, plus the hand-written `document`
  module (`SystemDocument`, `read_document`, `write_document`).
- PEP 561 `py.typed` marker; the package ships as fully typed.
- `__version__` and `__schema_version__` for runtime provenance.
- Schema-version stamp on `SystemDocument` and `PortfolioDocument`: readers check
  `schema_version` on the raw JSON before decoding and raise `SchemaVersionError`
  (`check_schema_version`); writers stamp the shipped schema version and encode
  canonically (absent, null and default-valued optional properties omitted).
  `write_document(..., schema_version="source")` keeps an older stamp after
  validating against that version's strict bundle (optional extra
  `source-version`); `upgrade_document` and `upgrade_portfolio_document` re-stamp.
  Strict bundles ship in `power_openapi_models/bundles/`.

### Added — TypeScript (`@sienna-platform/power-openapi-models`, npm)

- zod schemas for the same six domains, generated from the same schemas, with
  `zod.input`/`zod.output` types inferred from them. Runtime validation at
  parity with pydantic, not compile-time types only.
- Subpath exports per domain plus `./document`, dual ESM/CJS with `.d.ts`.
- `zod` is a **peer** dependency (`^4`), so a consumer cannot end up with two
  copies of zod. The generated code uses the zod v4 API.
- Hand-written `document.ts` mirroring `Core/SystemDocument.json`, the
  counterpart of Python's `document.py`.
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
- Multi-language layout: `python/`, `typescript/`, and `rust/`.
  Shared at the root: the `.schema-version` pin, the fixtures both languages
  round-trip, `codegen/`, and the cross-language check.
- `scripts/check_version_sync.py` — a `v*` tag cannot publish one language at a
  version the others do not carry, and with `--require` cannot silently publish
  nothing.
- A Python↔TypeScript and Python↔Rust equivalence gate in CI, both blocking.
  `check_cross_language.py --no-julia` runs them without the Julia arm, which
  needs a `PowerOpenAPIModels` checkout matching the pinned schema.
- `release-rust.yml`, publishing from the same `v*` tag over crates.io trusted
  publishing, and a Rust regeneration-drift job.

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

- **`openapi-to-rust` had its own version of the same defects**, each found by the
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

[0.1.0]: https://github.com/Sienna-Platform/power-openapi-models/releases/tag/v0.1.0

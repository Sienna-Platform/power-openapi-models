# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Unreleased

First release. Two packages, one version, one tag, one schema pin.

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

[0.1.0]: https://github.com/Sienna-Platform/power-openapi-models/releases/tag/v0.1.0

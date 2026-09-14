# power-openapi-models (Rust)

> [!NOTE]
> **Upcoming — not yet implemented.** There is no crate here yet and nothing
> to install. This directory is a reserved slot with a documented plan, so
> that adding Rust is a new directory rather than a restructuring of the
> repo.

Planned: typed Rust models for the Sienna power system data format — every
component, association, and time series row as a `serde` type generated from
the same OpenAPI schemas as the Python and TypeScript packages.

## What ships today

| Language | Package | Status |
|---|---|---|
| Python | [`power-openapi-models`](../python/) | Released |
| TypeScript | [`@sienna-platform/power-openapi-models`](../typescript/) | Released |
| Rust | this directory | **Upcoming** |

## The plan

**Generator.** Most likely [`typify`](https://github.com/oxidecomputer/typify),
which turns JSON Schema into `serde`-derived Rust types.
[`progenitor`](https://github.com/oxidecomputer/progenitor) builds on it for
OpenAPI documents. The six SiennaSchemas specs carry **no `paths`** — they are
schema-only — so only the type-generation half of either tool applies, exactly
as with orval on the TypeScript side.

**Versioning.** Rust joins the existing lockstep: one version, one `v*` tag,
one `.schema-version` pin shared by every language. Adding it means adding a
`rust/Cargo.toml` entry to `MANIFESTS` in
[`scripts/check_version_sync.py`](../scripts/check_version_sync.py) and a
`release-rust.yml` alongside the other two release workflows. Nothing else in
the release machinery changes.

**Equivalence gate.** [`scripts/check_cross_language.py`](../scripts/check_cross_language.py)
compares the generated surfaces field by field — names, requiredness, enum
values, scalar kinds, and defaults. A Rust arm returns the same `Surface`
shape as the Python, TypeScript, and Julia arms, so it inherits the guard that
refuses to report agreement when nothing was actually compared.

## Before generating anything here

Both existing generators dropped schema defaults somewhere, and one invented a
default the schema never declared — each a real behavioural difference between
packages built from one schema. Assume `typify` has its own version of this.
The fix-function docstrings in [`codegen/python/postprocess.py`](../codegen/python/postprocess.py)
and [`codegen/typescript/postprocess.ts`](../codegen/typescript/postprocess.ts)
name every defect found so far; the equivalence gate is what caught them.

Two lessons that cost real time, both recorded in
[`scripts/check_cross_language.py`](../scripts/check_cross_language.py):
compare what the codec puts on the wire, not what the struct declaration says
(`#[serde(rename)]` is where Rust will hide this), and a check that compares
nothing must fail rather than pass.

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for how generation, postprocessing,
and the release gates fit together. The existing
[`codegen/python/`](../codegen/python/) and
[`codegen/typescript/`](../codegen/typescript/) pipelines are the model to
follow: generate, then apply targeted fixes in a postprocess step, each fix a
single function documenting the generator behaviour it works around. Never
hand-edit generated output.

## License

BSD 3-Clause. See [LICENSE](../LICENSE).

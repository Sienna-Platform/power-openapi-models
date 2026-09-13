# power-openapi-models

Typed models for the Sienna power system data format — every component,
association, and time series row, generated from one set of OpenAPI schemas
and shipped as a matched package per language.

**What this is not:** a power-flow solver, an optimization framework, or a
simulation engine. These models carry no numerics; they are the input
format, not the tool.

## Packages

| Language | Package | Where |
|---|---|---|
| Python | [`power-openapi-models`](https://pypi.org/project/power-openapi-models/) on PyPI | [`python/`](python/) |
| TypeScript | [`@sienna-platform/power-openapi-models`](https://www.npmjs.com/package/@sienna-platform/power-openapi-models) on npm | [`typescript/`](typescript/) |
| Rust | planned | [`rust/`](rust/) |

Each package's own README covers install, quickstart, and API details for
that language.

## One schema, every language

`.schema-version` at the repo root pins the exact SiennaSchemas release every
language package is generated from. All packages ship in lockstep: one
version number, one `v*` tag, released to every registry at once.

## License

BSD 3-Clause. See [LICENSE](LICENSE).

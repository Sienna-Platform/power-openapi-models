# Multi-language packaging for power-openapi-models 0.1.0

Target: ship `power-openapi-models` 0.1.0 to **PyPI** and
`@sienna-platform/power-openapi-models` 0.1.0 to **npm** from one repo, one schema
pin, one tag — with a slot prepared for Rust.

Branch: `jd/multi-language-packaging`. Repo: `/Users/jdlara/cache/psy6/power-openapi-models`.

## Decisions (settled, do not relitigate)

| Decision | Choice |
|---|---|
| Repo layout | Symmetric monorepo: `python/`, `typescript/`, `rust/` slot, shared root |
| TS output | Orval `client: 'zod'` — runtime validation at parity with pydantic |
| npm shape | One package, six subpath exports (mirrors the Python distribution) |
| npm name | `@sienna-platform/power-openapi-models` |
| Versioning | Lockstep — one version, one `v*` tag fans out to every registry |
| Parity scope | Full: hand-written `document.ts` **and** a TS arm on the cross-language gate |
| Dedup strategy | **Approach A** — postprocess rewrite, mirroring `scripts/postprocess.py` |

## Verified facts this design rests on

These were measured against orval 8.32.0 and the current SiennaSchemas checkout.
Do not re-derive them; do re-verify if orval is upgraded.

1. **All six OpenAPI docs have zero `paths`.** They are schema-only. Orval's
   client/hook generation is inapplicable; only its model and zod output matter.
2. **`client: 'zod'` works on pathless specs.** It emits one zod schema per
   component schema plus `zod.input`/`zod.output` type aliases.
3. **Orval demands an explicit external-`$ref` allowlist.** Globs (`**/*.json`)
   are rejected; every referenced file must be enumerated by relative path.
   Hence the config must be generated, not hand-maintained.
4. **Orval has no ref→module mapping.** Its config surface is `externalRefs`,
   `indexFiles`, `namingConvention`, `schemas` — there is no equivalent of
   datamodel-codegen's `--external-ref-mapping`, which the Python `Makefile`
   relies on for four of its six domains. Duplication must therefore be solved
   after generation.
5. **Measured duplication** (real schema exports, `*Default` consts excluded):

   | Domain | Schema exports | Duplicated from `core`/`infrastructure_core` |
   |---|---|---|
   | `infrastructure_core` | 20 | — |
   | `core` | 67 | 12 |
   | `operations` | 126 | 52 |
   | `investments` | 60 | 38 |
   | `dynamics` | 12 | 3 |
   | `timeseries` | 50 | 1 |

   ~106 duplicate definitions total.
6. **`*Default` constants are load-bearing, not noise.** `core.zod.ts` has 1783
   `*Default` consts and exactly 1783 `.default(...)` call sites consuming them.
   They must keep working; they must not be public API.
7. **Orval emits the zod v4 API** (`zod.int()`, which zod v3 lacks). zod v4 is a
   hard floor.
8. **`Core/SystemDocument.json` is deliberately excluded from all six specs** —
   which is why `document.py` and the Julia `document.jl` are hand-written.
   `document.ts` becomes the third hand-written mirror. See Risks.

## Target layout

```
power-openapi-models/
├── .schema-version              # unchanged — ONE pin, all languages
├── CHANGELOG.md                 # one changelog (lockstep)
├── LICENSE
├── README.md                    # becomes a router to python/ and typescript/
├── package.json                 # PRIVATE workspace root: codegen toolchain only
├── bun.lock
├── Makefile                     # generate-python / generate-typescript / check
├── fixtures/                    # MOVED from tests/fixtures — shared by both languages
│   ├── case14_operations.NATURAL_UNITS.json
│   └── case14_operations.COMPONENT_BASE.json
├── codegen/
│   ├── Dockerfile               # MOVED from root; gains node for orval
│   ├── python/postprocess.py    # MOVED from scripts/
│   └── typescript/
│       ├── gen-orval-config.ts  # NEW — emits the $ref allowlist + six projects
│       └── postprocess.ts       # NEW — approach A
├── scripts/
│   └── check_cross_language.py  # STAYS at root — cross-language by definition
├── python/
│   ├── pyproject.toml
│   ├── src/power_openapi_models/
│   ├── tests/                   # minus fixtures/
│   └── scripts/                 # check_json_compat.py, check_typecompleteness.py
├── typescript/
│   ├── package.json             # THE PUBLISHED package
│   ├── tsconfig.json
│   ├── tsup.config.ts
│   ├── orval.config.ts          # GENERATED but COMMITTED
│   ├── src/
│   │   ├── index.ts
│   │   ├── document.ts          # hand-written mirror of Core/SystemDocument.json
│   │   ├── infrastructure_core/{models.ts,index.ts}
│   │   ├── core/{models.ts,index.ts}
│   │   ├── operations/{models.ts,index.ts}
│   │   ├── investments/{models.ts,index.ts}
│   │   ├── dynamics/{models.ts,index.ts}
│   │   └── timeseries/{models.ts,index.ts}
│   └── tests/
└── rust/README.md               # the plan, no code
```

Domain directory names mirror Python exactly, including the underscore:
`openapi-infrastructure-core.json` → `infrastructure_core/`.

### Why two `package.json` files

The root one is `"private": true` and holds orval, typescript, tsup — the codegen
toolchain. `typescript/package.json` declares only `zod` as a peer and is what
publishes. Collapsing them would ship the whole codegen toolchain as dependency
metadata on a data-model package.

### Why `fixtures/` is promoted to the root

Python and TS must round-trip the *same bytes* or "parity" is an unchecked claim.
Leaving fixtures under `python/tests/` would make the TS suite reach sideways into
another language's test directory.

## Generation pipeline

`make generate-typescript`:

1. **`codegen/typescript/gen-orval-config.ts`** walks `$SCHEMA_DIR` for every
   `*.json` under `Core/ Operations/ Dynamics/ Investments/ TimeSeries/`, and
   writes `typescript/orval.config.ts`: the allowlist (fact 3) plus six projects,
   each `client: 'zod'`, `mode: 'single'`, target
   `typescript/src/<domain>/models.ts`.
   The config is **committed** so CI need not regenerate it; CI asserts it is
   up to date by regenerating into a temp file and diffing.
2. **`orval --config typescript/orval.config.ts`**.
3. **`codegen/typescript/postprocess.ts`** (below).
4. Format the result.

### Postprocess — approach A

Mirrors `codegen/python/postprocess.py` in algorithm and in failure mode.

1. **Ownership map.** The canonical owner of a schema name is the domain whose
   spec defines it, resolved in precedence order
   `infrastructure_core` → `core` → {`operations`, `investments`, `dynamics`,
   `timeseries`}.
2. **Rewrite duplicates.** For each non-owner domain holding a duplicate name,
   compare the normalized body text against the owner's.
   - Identical → delete the block and emit
     `export { X } from '../<owner>/models';`, carrying the companion
     `export type X` / `export type XOutput` aliases with it.
   - **Different → fail loudly with a diff.** Never silently prefer one. This is
     exactly `dedupe_core_against_infrastructure_core`'s contract on the Python
     side.
3. **Demote `*Default` consts.** Drop the `export` keyword so they stay
   functional (fact 6) but leave the public surface. When deleting a duplicate
   block, delete its `*Default` consts **only if unreferenced elsewhere in the
   file** — some are shared with schemas that are not duplicates.
4. **Emit `index.ts`** per domain re-exporting `./models`.

## TypeScript package surface

- `name: "@sienna-platform/power-openapi-models"`, `version: "0.1.0"`,
  `"type": "module"`, `"sideEffects": false`, `"files": ["dist"]`.
- `peerDependencies: { "zod": "^4" }` (fact 7). zod is a peer, not a dependency,
  so a consumer cannot end up with two zod copies and the instanceof-style
  failures that follow.
- Build with **tsup**, `format: ['esm', 'cjs']`, `dts: true`. Dual output because
  ESM-only would exclude a large slice of Node consumers at 0.1.0.
- `exports` map: `.` plus the six domains plus `./document`.
- `document.ts` is **hand-written**, mirroring `Core/SystemDocument.json` field
  for field, and is the TS counterpart of `python/src/power_openapi_models/document.py`.
  It exports the `SystemDocument` zod schema (pure, isomorphic) and
  `readDocument`/`writeDocument` (which use `node:fs`, matching what `document.py`
  does).

## Cross-language gate

Extend `scripts/check_cross_language.py`. It already has `load_julia_surface` and
`load_python_surface` feeding a `compare(julia, python)` — that is the seam.

- Add **`load_typescript_surface()`** parsing `typescript/src/*/models.ts`:
  field names; `.optional()` → not required; `zod.int()`/`zod.number()`/
  `zod.string()`/`zod.boolean()` → scalar kind; `zod.enum([...])` → allowed
  values; `.default(X)` → default, resolved through the `*Default` const.
- Generalize `compare(julia, python)` → `compare(a, b, label_a, label_b)`.
- CLI grows `--ts typescript/`; the run performs Python↔Julia **and** Python↔TS.
- `EXEMPTIONS` gains a TS section, under the same rules already documented in
  that file's docstring: a specific `type.field`, a one-line reason, a removal
  condition. Never a category, never a wildcard.

Expect the gate to surface real divergences on first run. **Report them; do not
paper over them by widening EXEMPTIONS.** One already suspected: several
`power_units` fields carry a pydantic default on the Python side while the zod
schema emits no `.default()`.

### What the audit of this script actually found (2026-09-12)

The script was passing **vacuously**: it matched `Base.@kwdef mutable struct`
while the Julia generator emits `Base.@kwdef struct`, so it parsed zero structs,
compared zero types, and printed "Surfaces agree" with exit 0. Fixed, plus a
guard that refuses to report agreement when nothing was compared. That guard is
the reason the TS arm must return the same `Surface` shape rather than its own.

Of the 666 divergences that surfaced once it worked:

- **352 were false positives.** Julia snake_cases the *struct field* (`ta_tb`)
  but `_decode`/`_encode` use the schema key (`"Ta_Tb"`). The wire format is
  correct and documents round-trip. The check must compare JSON keys, not Julia
  identifiers. **Do not re-report this as a casing bug** — reading the struct
  declaration without the codec is what caused the misread.
- **290 are real**: Julia leaves an omitted defaulted field `ABSENT` where
  Python materializes the schema default. Verified by running both
  (`SEXS.V_ref`, schema default `1.0` → Julia `ABSENT`, Python `1.0`). This is
  pre-existing, lives in another repo, and is filed separately — see
  `.claude/plans/DRAFT-issue-poweropenapimodels-defaults.md`.

**Gate policy for this PR:** Python↔TypeScript is a hard CI gate and must be
green. Python↔Julia runs **report-only** — printing every divergence and its
count loudly, exiting 0, stating in the output that it is deliberately not
gating and why. Not by suppression, not by EXEMPTIONS, not by a silent default.

## CI and release

- **`test.yml`** — keep the Python job with corrected paths; add a TypeScript job
  (install, generate-check, typecheck, test, build). Add a **version-sync step**
  asserting `pyproject.toml` version == `typescript/package.json` version.
- **`release.yml`** splits into `release-python.yml` and `release-typescript.yml`,
  both triggered on `v*`. Python keeps PyPI trusted publishing (OIDC). npm
  publishes with `--provenance` and `id-token: write`. Both assert the tag
  matches the manifest version before publishing.
- **`update-schema.yml`** — regenerate **both** languages and validate both.
- **`build-codegen.yml`** — `codegen/Dockerfile` now needs node alongside python.
- **`rust/README.md`** — records that Rust joins under the same lockstep tag, and
  that the likely generator is `typify`/`progenitor` over the same specs. No code.

## Risks

1. **`SystemDocument` is now hand-mirrored in three languages** (Python, Julia,
   TS) and a fourth is planned. The real fix is upstream: include
   `Core/SystemDocument.json` in a selector spec so it generates. That is a
   SiennaSchemas change and is **out of scope here** — file a follow-up issue.
2. **The path rewrite is where a mistake hides.** The `git mv` is mechanical; the
   ~30 path references across workflows, `Makefile`, `pyproject.toml`,
   `postprocess.py`, and `check_cross_language.py` are not. Every one must be
   verified by running the thing, not by reading it.
3. ~~**The npm org `sienna-platform` does not exist yet.**~~ Created 2026-09-12.
   Still required before the first publish: add this repo as a **trusted
   publisher** on the npm org so `release-typescript.yml` can publish via OIDC
   with `--provenance` and no stored token.
4. **PyPI `power-openapi-models` is unclaimed, so 0.1.0 is a first publish.**
   Trusted publishing has no existing project to attach OIDC to, so a **pending
   publisher** must be configured on PyPI before the first upload. The current
   `release.yml` assumes the project already exists.
5. **Orval upgrades can silently reshape output.** Pin it exactly in the root
   `package.json`, as the `Dockerfile` already pins datamodel-code-generator and
   ruff for the same reason.

## Out of scope

- Publishing anything. No `npm publish`, no PyPI upload, no tag, no commit
  without an explicit instruction.
- Any Rust implementation beyond the directory and its README.
- Changes to SiennaSchemas.
- Bumping the version past 0.1.0.

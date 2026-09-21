# Contributing

## The models are generated

Everything under `python/src/power_openapi_models/*/models.py` is **generated
output**. An edit there is erased by the next regeneration and the drift
check will not flag it as intentional.

Fixes belong in one of two upstream places:

1. **[SiennaSchemas](https://github.com/Sienna-Platform/SiennaSchemas)** — the source of truth for
   fields, types, defaults, and unit annotations. A wrong field or a missing
   type is a schema bug.
2. **`codegen/python/postprocess.py`** — for defects the code generator introduces
   that the schema cannot express. Each fix is one function with a docstring
   explaining the generator behavior it works around.

A `<Base><N>` class whose `<Base>` also exists is a generator alias leak; the
cure is naming the inline object or enum as a `$defs` entry in the SiennaSchemas
source, rather than leaving it anonymous at the reference site.
`python/tests/test_public_api.py` fails on these.

`python/src/power_openapi_models/document.py` is the one exception: it is
hand-written, not generated, and mirrors `Core/SystemDocument.json` by hand.

## Regenerating

Point `SCHEMA_DIR` at a local SiennaSchemas checkout and run from the repo
root. Each language regenerates independently.

### Python

```bash
make generate-python SCHEMA_DIR=../SiennaSchemas
```

This runs `datamodel-codegen` once per domain module, then
`codegen/python/postprocess.py`, which de-duplicates `core` against
`infrastructure_core` and applies a set of targeted fixes for known
datamodel-codegen gaps (see the docstring on each fix function in
`codegen/python/postprocess.py`).

#### Via the pre-built codegen image

This covers the **Python** generation only. It pins
`datamodel-code-generator` and `ruff` because both shape the generated output.
TypeScript pins `orval` exactly in the root `package.json` for the same reason
and regenerates on the runner instead, rather than coupling two independent
generators into one image rebuild.

```bash
make generate-docker
```

Pulls `$(CODEGEN_IMAGE)` (see the `Makefile`) and runs the Python generation
inside a container, mounting `SCHEMA_DIR` read-only and this repo as the
output directory. The image itself is built and pushed by
`.github/workflows/build-codegen.yml` from this repo's `codegen/Dockerfile`.

### TypeScript

```bash
make generate-typescript SCHEMA_DIR=../SiennaSchemas
```

Three stages:

1. `codegen/typescript/gen-orval-config.ts` writes `typescript/orval.config.ts`.
   It is generated rather than hand-written because orval requires every
   external `$ref` target to be enumerated explicitly — it rejects globs — so
   the allowlist has to be derived from the schema tree. The result is
   committed, and CI fails if it is stale.
2. `orval` generates one zod module per domain.
3. `codegen/typescript/postprocess.ts` deduplicates and applies targeted fixes.

The postprocess mirrors `codegen/python/postprocess.py`, including its failure
mode: orval generates each domain independently, so ~106 shared types are
emitted more than once. Each duplicate is rewritten into a re-export from its
owning domain **only if the two bodies are identical** — otherwise it aborts
with a diff and writes nothing, rather than guessing which copy wins.

Two things it does that are worth knowing about:

- **`*Default` consts are demoted, not deleted.** They are load-bearing: every
  one is referenced by a `.default(...)` call. The postprocess drops only the
  `export` keyword, so they keep working without becoming public API.
- **Single-valued enums are canonicalized to their literal form.** orval renders
  the same `$ref`'s discriminator as `zod.enum(['X'])` in one domain and
  `zod.literal("X")` in another, depending on whether that schema also appears
  in a discriminated union in the importing spec. The two are interchangeable
  at runtime and in inferred type; a multi-valued enum difference is real and
  still fails loudly.

Note the postprocess runs on orval's **raw** output — one line per declaration,
keys quoted — not the prettier-formatted result. Pattern-matching fixes must
match that form.

## Running the checks

From the repo root:

```bash
cd python && pip install -e ".[dev]"
make lint        # ruff check + ruff format --check
make typecheck    # pyright --verifytypes power_openapi_models
make validate     # import smoke check + pytest
```

Or the individual pieces, from `python/`:

```bash
cd python
ruff check .
ruff format --check .
pytest tests/ -q
pyright --verifytypes power_openapi_models
```

For TypeScript, from `typescript/`:

```bash
npm ci                 # from the repo root
npx tsc --noEmit
npm test
npm run build
```

And the cross-language equivalence gate, from the repo root:

```bash
python3 scripts/check_cross_language.py --ts typescript/ \
    --julia ../PowerOpenAPIModels --julia-report-only
```

**Python↔TypeScript is a hard gate** and must stay green. Python↔Julia runs
report-only: it prints every divergence but does not fail, because ~290 of them
are a pre-existing bug in `PowerOpenAPIModels` where Julia leaves an omitted
defaulted field absent while Python materializes the schema default. That is
filed separately; it is not this repo's to fix, and it is not suppressed.

`python/tests/test_readme.py` executes every fenced ```` ```python ```` block in
`python/README.md`. If you change a README example, make sure it still runs — a
block that should illustrate something without running (pseudo-code, a
deliberate error) must be fenced as ```` ```text ```` instead.

## Releasing

Versioning is **lockstep**: every language package carries the same version, and
one `vX.Y.Z` tag publishes all of them. That is only meaningful because every
package is generated from the one `.schema-version` pin — the version means
"this schema pin, these models", in any language.

`scripts/check_version_sync.py` enforces it. Both release workflows gate on it
with `--require python,typescript`, so a tag cannot publish one language at a
version the others do not carry, and cannot silently publish nothing if a
manifest is missing.

To cut a release:

1. Add a dated entry to `CHANGELOG.md`.
2. Bump the version in **both** `python/pyproject.toml` and
   `typescript/package.json`, then confirm:

   ```bash
   python3 scripts/check_version_sync.py --require python,typescript
   ```

3. Commit, tag `vX.Y.Z`, and push the tag. `release-python.yml` and
   `release-typescript.yml` both fire from it.

### First publish, once per registry

Neither registry can be published to from CI until its trust is established,
and the two work differently:

- **PyPI** supports a *pending publisher*. Configure it on PyPI before tagging
  and the very first CI publish works with no token.
- **npm has no equivalent.** A trusted publisher can only be attached to a
  package that already exists, so the first version must be published by hand:

  ```bash
  cd typescript && npm publish --access public
  ```

  Then add this repo and `release-typescript.yml` as a trusted publisher on the
  `@sienna-platform` org. Every release after that runs from CI over OIDC with
  no stored token.

Until that is done `release-typescript.yml` fails rather than falling back to a
stored secret, which is deliberate.

See `CHANGELOG.md` for the format and history.

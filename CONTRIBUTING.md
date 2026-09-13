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

Point `SCHEMA_DIR` at a local SiennaSchemas checkout and run, from the repo root:

```bash
make generate-python SCHEMA_DIR=../SiennaSchemas
```

This runs `datamodel-codegen` once per domain module, then
`codegen/python/postprocess.py`, which de-duplicates `core` against
`infrastructure_core` and applies a set of targeted fixes for known
datamodel-codegen gaps (see the docstring on each fix function in
`codegen/python/postprocess.py`).

### Via the pre-built codegen image

```bash
make generate-docker
```

Pulls `$(CODEGEN_IMAGE)` (see the `Makefile`) and runs the same generation
inside a container, mounting `SCHEMA_DIR` read-only and this repo as the
output directory. The image itself is built and pushed by
`.github/workflows/build-codegen.yml` from this repo's `codegen/Dockerfile`.

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

`python/tests/test_readme.py` executes every fenced ```` ```python ```` block in
`python/README.md`. If you change a README example, make sure it still runs — a
block that should illustrate something without running (pseudo-code, a
deliberate error) must be fenced as ```` ```text ```` instead.

## Releasing

Version is static in `python/pyproject.toml`. To cut a release:

1. Add a dated entry to `CHANGELOG.md`.
2. Bump the version in `python/pyproject.toml` and commit.
3. Tag `vX.Y.Z` and push the tag — `.github/workflows/release.yml` builds the
   sdist and wheel, runs `twine check`, and publishes to PyPI via trusted
   publishing (OIDC, no stored tokens).

See `CHANGELOG.md` for the format and history.

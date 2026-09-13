SCHEMA_DIR ?= ../SiennaSchemas
CODEGEN_IMAGE ?= ghcr.io/sienna-platform/power-openapi-models/codegen:latest
PKG_DIR := python/src/power_openapi_models
# `--allow-remote-refs` (previously passed to the infrastructure_core and core
# invocations below) does not exist in datamodel-code-generator 0.55.0 (the Dockerfile's
# pin) and fails immediately: "unrecognized arguments: --allow-remote-refs". Confirmed
# generation of every domain still resolves same-filesystem external $refs correctly
# without it.
CODEGEN := datamodel-codegen --input-file-type openapi \
	--output-model-type pydantic_v2.BaseModel \
	--formatters ruff-format \
	--use-enum-values-in-discriminator \
	--disable-timestamp
CORE_REF := --external-ref-mapping "Core/common.json=power_openapi_models.core.models"

.PHONY: generate generate-python generate-typescript generate-docker clean validate lint typecheck check

generate: generate-python

generate-python:
	@# infrastructure_core is its own subpackage, generated straight from
	@# openapi-infrastructure-core.json -- see SiennaSchemas' six-package
	@# contract (openapi-infrastructure-core.json, scripts/check_layering.py
	@# there). It has no dependencies of its own, so no ref mapping is needed.
	@echo "==> Generating infrastructure_core"
	$(CODEGEN) \
	  --input $(SCHEMA_DIR)/openapi-infrastructure-core.json \
	  --output $(PKG_DIR)/infrastructure_core/models.py

	@# core is generated with no ref mapping: --external-ref-mapping keys on a
	@# $$ref's file path, not the individual $$def, so mapping Core/common.json
	@# wholesale would misroute core's own types that live in the same file.
	@# postprocess.py's dedupe_core_against_infrastructure_core rewrites the
	@# resulting duplicates into imports -- see its docstring for why.
	@echo "==> Generating core"
	$(CODEGEN) \
	  --input $(SCHEMA_DIR)/openapi-core.json \
	  --output $(PKG_DIR)/core/models.py

	@echo "==> Generating operations"
	$(CODEGEN) $(CORE_REF) \
	  --input $(SCHEMA_DIR)/openapi-operations.json \
	  --output $(PKG_DIR)/operations/models.py

	@echo "==> Generating investments"
	$(CODEGEN) $(CORE_REF) \
	  --input $(SCHEMA_DIR)/openapi-investments.json \
	  --output $(PKG_DIR)/investments/models.py

	@echo "==> Generating dynamics"
	$(CODEGEN) $(CORE_REF) \
	  --input $(SCHEMA_DIR)/openapi-dynamics.json \
	  --output $(PKG_DIR)/dynamics/models.py

	@echo "==> Generating timeseries"
	$(CODEGEN) $(CORE_REF) \
	  --input $(SCHEMA_DIR)/openapi-timeseries.json \
	  --output $(PKG_DIR)/timeseries/models.py

	@echo "==> Post-processing"
	SCHEMA_DIR=$(SCHEMA_DIR) python3 codegen/python/postprocess.py

	@# Keep the packaged copy of .schema-version in sync so
	@# power_openapi_models.__schema_version__ never goes stale after a regen.
	cp .schema-version $(PKG_DIR)/_schema_version.txt

generate-typescript:
	@# gen-orval-config.ts walks $(SCHEMA_DIR) itself (Core/ Operations/
	@# Dynamics/ Investments/ TimeSeries/) to build orval's required
	@# external-$ref allowlist -- orval rejects globs, unlike datamodel-codegen
	@# -- and to emit the six per-domain projects. Regenerated every run so a
	@# non-default SCHEMA_DIR is always reflected, even though the result is
	@# also committed (see typescript/orval.config.ts).
	@echo "==> Generating typescript/orval.config.ts"
	SCHEMA_DIR=$(SCHEMA_DIR) npx tsx codegen/typescript/gen-orval-config.ts

	@echo "==> Running orval"
	SCHEMA_DIR=$(SCHEMA_DIR) npx orval --config typescript/orval.config.ts

	@# Rewrites cross-domain duplicate schemas (orval has no ref-to-module
	@# mapping, unlike datamodel-codegen's --external-ref-mapping the Python
	@# side relies on) into re-exports of their canonical owner -- failing
	@# loudly, never guessing, if a "duplicate" isn't actually identical. Also
	@# reads $(SCHEMA_DIR) directly (same as gen-orval-config.ts above) to
	@# restore schema defaults orval drops and to rename an orval-mangled
	@# acronym export back to its schema title. See codegen/typescript/postprocess.ts.
	@echo "==> Post-processing"
	SCHEMA_DIR=$(SCHEMA_DIR) npx tsx codegen/typescript/postprocess.ts

	@echo "==> Formatting"
	npx prettier --write "typescript/orval.config.ts" "typescript/src/**/*.ts"

generate-docker:
	docker run --rm \
	  -v $(abspath $(SCHEMA_DIR)):/schemas:ro \
	  -v $(CURDIR):/output \
	  $(CODEGEN_IMAGE)

clean:
	rm -f $(PKG_DIR)/*/models.py

validate:
	cd python && python3 -c "import power_openapi_models; print('Import OK')"
	cd python && pytest tests/ -v

lint:
	ruff check python/ scripts/ codegen/
	ruff format --check python/ scripts/ codegen/

typecheck:
	@# python/scripts/check_typecompleteness.py runs `pyright --verifytypes`
	@# itself (with PYTHONPATH=python/src -- an editable install alone does
	@# not let --verifytypes find a src/-layout package) and enforces a
	@# completeness floor explicitly, rather than trusting pyright's raw exit
	@# code: that exit code reflects whether any diagnostic was printed, not
	@# whether the score cleared a bar, so it is not on its own an honest gate.
	cd python && python3 scripts/check_typecompleteness.py

check: lint typecheck validate

SCHEMA_DIR ?= ../SiennaSchemas
CODEGEN_IMAGE ?= ghcr.io/sienna-platform/power-openapi-models/codegen:latest
PKG_DIR := src/power_openapi_models
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

.PHONY: generate generate-docker clean validate lint typecheck check

generate:
	@# infrastructure_core is its own subpackage, generated straight from
	@# openapi-infrastructure-core.json -- see SiennaSchemas' six-package
	@# contract (openapi-config-infrastructure-core.json, scripts/check_layering.py
	@# there). It has no dependencies of its own, so no ref mapping is needed.
	@echo "==> Generating infrastructure_core"
	$(CODEGEN) \
	  --input $(SCHEMA_DIR)/openapi-infrastructure-core.json \
	  --output $(PKG_DIR)/infrastructure_core/models.py

	@# core is generated straight from openapi-core.json, no merge. Its own
	@# schema graph still reaches into Core/common.json for several of
	@# infrastructure_core's 20 types (UnitSystem, the function-data family,
	@# XY_Coords, ...) -- common.json is the $defs home for BOTH selectors,
	@# and datamodel-codegen's --external-ref-mapping keys on a $ref's *file
	@# path*, not the individual $def, so mapping that file wholesale to
	@# power_openapi_models.infrastructure_core.models would misroute core's
	@# own types (CostCurve, StartUp, CurveStyle, ...) that live in the same
	@# file but aren't part of infrastructure_core's selection. There is no
	@# per-$def mapping in this datamodel-codegen version, so core is
	@# generated with no ref mapping at all: it locally redefines whichever
	@# of the 20 infrastructure_core types its own schema graph reaches, and
	@# scripts/postprocess.py rewrites those duplicate class bodies into
	@# imports afterward -- failing loudly if a body it finds in both files
	@# ever differs -- so nothing is defined twice in the committed output.
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
	python3 scripts/postprocess.py

	@# Keep the packaged copy of .schema-version in sync so
	@# power_openapi_models.__schema_version__ never goes stale after a regen.
	cp .schema-version $(PKG_DIR)/_schema_version.txt

generate-docker:
	docker run --rm \
	  -v $(abspath $(SCHEMA_DIR)):/schemas:ro \
	  -v $(CURDIR):/output \
	  $(CODEGEN_IMAGE)

clean:
	rm -f $(PKG_DIR)/*/models.py

validate:
	python3 -c "import power_openapi_models; print('Import OK')"
	pytest tests/ -v

lint:
	ruff check .
	ruff format --check .

typecheck:
	@# scripts/check_typecompleteness.py runs `pyright --verifytypes` itself
	@# (with PYTHONPATH=src -- an editable install alone does not let
	@# --verifytypes find a src/-layout package) and enforces a completeness
	@# floor explicitly, rather than trusting pyright's raw exit code: that
	@# exit code reflects whether any diagnostic was printed, not whether the
	@# score cleared a bar, so it is not on its own an honest gate.
	python3 scripts/check_typecompleteness.py

check: lint typecheck validate

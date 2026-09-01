SCHEMA_DIR ?= ../SiennaSchemas
CODEGEN_IMAGE ?= ghcr.io/sienna-platform/power-openapi-models/codegen:latest
PKG_DIR := src/power_openapi_models
CODEGEN := datamodel-codegen --input-file-type openapi \
	--output-model-type pydantic_v2.BaseModel \
	--formatters ruff-format \
	--use-enum-values-in-discriminator \
	--disable-timestamp
CORE_REF := --external-ref-mapping "Core/common.json=power_openapi_models.core.models"

.PHONY: generate generate-docker clean validate

generate:
	@# infrastructure_core is its own subpackage, generated straight from
	@# openapi-infrastructure-core.json -- see SiennaSchemas' six-package
	@# contract (openapi-config-infrastructure-core.json, scripts/check_layering.py
	@# there). It has no dependencies of its own, so no ref mapping is needed.
	@echo "==> Generating infrastructure_core"
	$(CODEGEN) --allow-remote-refs \
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
	$(CODEGEN) --allow-remote-refs \
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
	python scripts/postprocess.py

generate-docker:
	docker run --rm \
	  -v $(abspath $(SCHEMA_DIR)):/schemas:ro \
	  -v $(CURDIR):/output \
	  $(CODEGEN_IMAGE)

clean:
	rm -f $(PKG_DIR)/*/models.py

validate:
	python -c "import power_openapi_models; print('Import OK')"
	pytest tests/ -v

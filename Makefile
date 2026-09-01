SCHEMA_DIR ?= ../SiennaSchemas
CODEGEN_IMAGE ?= ghcr.io/sienna-platform/power-openapi-models/codegen:latest
PKG_DIR := src/power_openapi_models
CODEGEN := datamodel-codegen --input-file-type openapi \
	--output-model-type pydantic_v2.BaseModel \
	--formatters ruff-format \
	--use-enum-values-in-discriminator \
	--disable-timestamp
CORE_REF := --external-ref-mapping "Core/common.json=power_openapi_models.core.models"
MERGED_CORE_SPEC := generated/openapi-core-merged.json

.PHONY: generate generate-docker clean validate

generate:
	@# SiennaSchemas splits its purely-administrative/association schemas (SupplementalAttribute-
	@# Association, GeographicInfo, DataSource, the shared MinMax/InOut/UpDown/... value types)
	@# into a separate `infrastructure-core` bundle -- see openapi-config-infrastructure-core.json
	@# and scripts/check_layering.py there. No datamodel-codegen equivalent of the Julia side's
	@# per-type file copy (reorganize.jl) exists, since datamodel-codegen emits one models.py per
	@# input spec rather than one file per type, so the two selectors' schemas are unioned into
	@# one temp spec first and core/models.py is generated from that in a single pass.
	@echo "==> Merging core + infrastructure-core specs"
	python3 scripts/merge_core_spec.py $(SCHEMA_DIR) $(MERGED_CORE_SPEC)

	@echo "==> Generating core"
	$(CODEGEN) --allow-remote-refs \
	  --input $(MERGED_CORE_SPEC) \
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
	rm -f $(PKG_DIR)/*/models.py $(MERGED_CORE_SPEC)

validate:
	python -c "import power_openapi_models; print('Import OK')"
	pytest tests/ -v

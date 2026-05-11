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

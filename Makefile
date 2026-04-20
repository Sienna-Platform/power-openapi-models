CODEGEN_IMAGE := ghcr.io/sienna-platform/power-openapi-models/codegen:latest

.PHONY: generate generate-local

generate:
	docker run --rm \
	  -v $(CURDIR)/openapi:/schemas:ro \
	  -v $(CURDIR):/output \
	  $(CODEGEN_IMAGE) \
	  /schemas /output

generate-local:
	docker build -t $(CODEGEN_IMAGE) .
	docker run --rm \
	  -v $(CURDIR)/openapi:/schemas:ro \
	  -v $(CURDIR):/output \
	  $(CODEGEN_IMAGE) \
	  /schemas /output

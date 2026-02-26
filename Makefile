CODEGEN_IMAGE := ghcr.io/myorg/power-codegen:latest

.PHONY: generate
generate:
	docker run --rm \
	  -v $(CURDIR)/schemas:/schemas:ro \
	  -v $(CURDIR):/output \
	  $(CODEGEN_IMAGE) \
	  --target python --schemas /schemas --output /output

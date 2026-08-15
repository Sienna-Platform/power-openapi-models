FROM python:3.12-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends make && \
    rm -rf /var/lib/apt/lists/*

# Pinned to uv.lock: both tools shape the generated output (ruff is the
# --formatters backend), so an unpinned image regenerates a different file
# from the same schemas.
RUN pip install --no-cache-dir datamodel-code-generator==0.55.0 ruff==0.15.7

WORKDIR /output
ENTRYPOINT ["make", "generate", "SCHEMA_DIR=/schemas"]

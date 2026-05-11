FROM python:3.12-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends make && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir datamodel-code-generator ruff

WORKDIR /output
ENTRYPOINT ["make", "generate", "SCHEMA_DIR=/schemas"]

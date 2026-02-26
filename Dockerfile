FROM python:3.12-slim-bookworm

# Install Node.js (for openapi-generator-cli) and Java (runtime dependency)
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs npm default-jre-headless && \
    rm -rf /var/lib/apt/lists/*

# Install openapi-generator-cli
RUN npm install -g @openapitools/openapi-generator-cli

# Install ruff
RUN pip install --no-cache-dir ruff

# Copy scripts into the image
COPY scripts/ /opt/scripts/
RUN chmod +x /opt/scripts/*.sh

ENTRYPOINT ["/opt/scripts/generate.sh"]

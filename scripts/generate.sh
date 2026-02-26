#!/usr/bin/env bash
# scripts/generate.sh
#
# Main entrypoint for code generation. Runs the full pipeline:
#   1. OpenAPI Generator (python target) for each domain
#   2. Reorganize stubs into package layout
#   3. Format with ruff
#
# Usage: generate.sh <schema-dir> <output-dir>
#   schema-dir  — directory containing core.yaml, operations.yaml, etc.
#   output-dir  — repository root (where src/, scripts/, etc. live)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

SCHEMA_DIR="${1:?Usage: generate.sh <schema-dir> <output-dir>}"
OUTPUT_DIR="${2:?Usage: generate.sh <schema-dir> <output-dir>}"

DOMAINS=(core operations investments dynamics)

# ── Step 1: Generate raw stubs ──────────────────────────────────────────────
echo "==> Generating Python stubs"
for domain in "${DOMAINS[@]}"; do
  echo "    → $domain"
  openapi-generator-cli generate \
    -i "$SCHEMA_DIR/${domain}.yaml" \
    -g python \
    -o "$OUTPUT_DIR/generated/${domain}" \
    --additional-properties=packageName="power_openapi_models_${domain}" \
    --skip-validate-spec \
    > /dev/null
done

# ── Step 2: Reorganize into package layout ──────────────────────────────────
echo "==> Reorganizing stubs"
bash "$SCRIPT_DIR/reorganize_stubs.sh"

# ── Step 3: Format and lint ─────────────────────────────────────────────────
echo "==> Formatting with ruff"
ruff format "$OUTPUT_DIR/src/power_openapi_models/" || true
ruff check --fix "$OUTPUT_DIR/src/power_openapi_models/" || true

echo "==> Generation complete"

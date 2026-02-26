#!/usr/bin/env bash
# scripts/reorganize_stubs.sh
#
# Redistributes auto-generated OpenAPI stubs into the package subfolders.
# Run from the repository root after openapi-generator has written to generated/.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GENERATED="$REPO_ROOT/generated"
PKG_ROOT="$REPO_ROOT/src/power_openapi_models"

DOMAINS=(core operations investments dynamics)

for domain in "${DOMAINS[@]}"; do
  gen_dir="$GENERATED/$domain"
  target="$PKG_ROOT/$domain"

  if [[ ! -d "$gen_dir" ]]; then
    echo "WARNING: $gen_dir not found, skipping $domain"
    continue
  fi

  echo "==> Processing $domain"

  # Clean previous generated source (preserve __init__.py template if manually maintained)
  rm -rf "$target/models" "$target/apis"
  mkdir -p "$target/models" "$target/apis"

  # Locate generated model and api files
  # openapi-generator python output structure varies; find .py files by convention
  GEN_MODEL_DIR=$(find "$gen_dir" -type d -name "models" | head -1)
  GEN_API_DIR=$(find "$gen_dir" -type d -name "apis" -o -type d -name "api" | head -1)

  # Copy model files
  if [[ -n "$GEN_MODEL_DIR" && -d "$GEN_MODEL_DIR" ]]; then
    cp "$GEN_MODEL_DIR/"*.py "$target/models/" 2>/dev/null || true
  fi

  # Copy API files
  if [[ -n "$GEN_API_DIR" && -d "$GEN_API_DIR" ]]; then
    cp "$GEN_API_DIR/"*.py "$target/apis/" 2>/dev/null || true
  fi

  # Ensure __init__.py in models/ and apis/
  for subdir in models apis; do
    init_file="$target/$subdir/__init__.py"
    if [[ ! -f "$init_file" ]]; then
      echo '"""Auto-generated."""' > "$init_file"
    fi
    # Auto-import all public names from each module
    {
      echo '"""Auto-generated."""'
      for f in "$target/$subdir/"*.py; do
        mod=$(basename "$f" .py)
        [[ "$mod" == "__init__" ]] && continue
        echo "from .${mod} import *"
      done
    } > "$init_file"
  done

  # Generate domain __init__.py
  cat > "$target/__init__.py" <<EOF
"""Auto-generated stubs for the $domain domain."""

from power_openapi_models.${domain} import models
from power_openapi_models.${domain} import apis

__all__ = ["models", "apis"]
EOF

  echo "    Done: $target"
done

# Clean up
echo "==> Cleaning generated/"
rm -rf "$GENERATED"

echo "==> Done. Review git diff before committing."

# power-openapi-models

Auto-generated Python models from NREL-Sienna power system OpenAPI schemas.

## Package Structure

The package is organized into four domain subpackages:

```
src/power_openapi_models/
├── core/          # Shared types, enums, base models
├── operations/    # Operations API stubs
├── investments/   # Investments API stubs
└── dynamics/      # Dynamics API stubs
```

## Installation

```bash
pip install power-openapi-models
```

## Usage

```python
# Import only what you need
from power_openapi_models.core.models import TimeSeries, NetworkTopology
from power_openapi_models.operations.models import Generator, Bus
from power_openapi_models.investments.apis import PortfolioApi

# Or import a whole domain
from power_openapi_models import operations
```

## Regenerating Stubs

Models are auto-generated from OpenAPI schemas in [SiennaSchemas](https://github.com/NREL-Sienna/SiennaSchemas). There are two ways to regenerate locally:

### Via pre-built image (pulls from GHCR)

```bash
make generate
```

### Via local Docker build

```bash
make generate-local
```

### Manual Docker commands

```bash
# Build the codegen image
docker build -t power-openapi-models-codegen .

# Run generation (mount schemas and repo root)
docker run --rm \
  -v $(pwd)/openapi:/schemas:ro \
  -v $(pwd):/output \
  power-openapi-models-codegen \
  /schemas /output
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

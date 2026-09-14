/**
 * The six SiennaSchemas entry specs and the package directories they generate
 * into. Shared so adding a seventh domain is one edit rather than two --
 * gen-orval-config.ts and postprocess.ts both need this list, and
 * gen-orval-config.ts calls main() at import time so it cannot be the home.
 *
 * Directory names mirror python/src/power_openapi_models/<domain> exactly,
 * including the underscore in infrastructure_core.
 */
export interface Domain {
  /** orval project name, and the generated directory name. */
  key: string;
  /** Entry spec filename under SCHEMA_DIR. */
  spec: string;
}

export const DOMAINS: ReadonlyArray<Domain> = [
  { key: "infrastructure_core", spec: "openapi-infrastructure-core.json" },
  { key: "core", spec: "openapi-core.json" },
  { key: "operations", spec: "openapi-operations.json" },
  { key: "investments", spec: "openapi-investments.json" },
  { key: "dynamics", spec: "openapi-dynamics.json" },
  { key: "timeseries", spec: "openapi-timeseries.json" },
];

export const DOMAIN_SPECS: ReadonlyArray<string> = DOMAINS.map((d) => d.spec);

/**
 * Hand-written (NOT generated): the SystemDocument and PortfolioDocument
 * containers and their JSON I/O.
 *
 * Counterpart of `power_openapi_models/document.py` and
 * `PowerOpenAPIModels.jl/src/system_document.jl` + `portfolio_document.jl`.
 * `Core/SystemDocument.json` and `Investments/PortfolioDocument.json` in
 * SiennaSchemas are authoritative for the two shapes; this module mirrors
 * their properties and `required` lists field for field.
 *
 * Both are hand-written for the same reason the schemas record: `components`
 * is a map from type name to an array of heterogeneous objects, which the
 * generator cannot express as typed buckets, so it skips the whole document
 * type.
 *
 * There is no document-level `unit_system` or `base_power`: every value is
 * interpretable from its own component blob alone, via that blob's own
 * basis-selector property (`power_units`, `parameter_units`, ...) and, for a
 * COMPONENT_BASE reading, that blob's own `base_power`. `SystemDocument`
 * forbids both fields outright.
 *
 * `components` and `supplemental_attributes` stay loosely typed
 * (`Record<string, unknown>` / arrays of it): they hold heterogeneous objects
 * keyed or discriminated by a type name this package cannot enumerate
 * statically.
 *
 * The other five association arrays (`supplemental_attribute_associations`,
 * `plant_associations`, `combined_cycle_associations`, `service_associations`,
 * `trading_hub_associations`) and `time_series_associations` all have
 * generated schemas (`infrastructure_core`'s `SupplementalAttributeAssociation`,
 * `operations`' `PlantAssociation`/`CombinedCycleAssociation`/
 * `ServiceAssociation`/`TradingHubAssociation`, `timeseries`'
 * `TimeSeriesAssociation`), so those fields are typed with them, mirroring
 * Python's import list.
 */

import { readFileSync, writeFileSync } from "node:fs";
import * as zod from "zod";

import { SupplementalAttributeAssociation } from "./infrastructure_core/models";
import {
  CombinedCycleAssociation,
  PlantAssociation,
  ServiceAssociation,
  TradingHubAssociation,
} from "./operations/models";
import {
  PortfolioFinancialData,
  RequirementAssociation,
} from "./investments/models";
import { TimeSeriesAssociation } from "./timeseries/models";

const genericRecord = zod.record(zod.string(), zod.unknown());

export const SystemDocument = zod
  .object({
    name: zod.string().nullable().optional().describe("Optional system name."),
    description: zod
      .string()
      .nullable()
      .optional()
      .describe("Optional free-text description of the system."),
    frequency: zod
      .number()
      .positive()
      .nullable()
      .optional()
      .describe("Nominal system frequency. Units: Hz."),
    components: zod
      .record(zod.string(), zod.array(genericRecord))
      .describe(
        'Components grouped by type name, e.g. `{"ACBus": [...], "ThermalStandard": [...]}`. Keys are the referenced schema\'s `title` and must be emitted in sorted order.',
      ),
    supplemental_attributes: zod
      .array(genericRecord)
      .describe(
        "Supplemental attributes in one flat array rather than bucketed by type; `supplemental_attribute_associations` carries the `attribute_type` discriminator a consumer needs to pick a converter.",
      ),
    supplemental_attribute_associations: zod
      .array(SupplementalAttributeAssociation)
      .describe(
        "Links each plain supplemental attribute to the entity it describes. One row per (attribute, entity) pair.",
      ),
    plant_associations: zod
      .array(PlantAssociation)
      .describe(
        "Links a power plant supplemental attribute to a generating unit and the group it belongs to within the plant.",
      ),
    combined_cycle_associations: zod
      .array(CombinedCycleAssociation)
      .describe(
        "Links a CombinedCycleBlock plant to a CT or CA unit and the HRSG it feeds into or receives from.",
      ),
    service_associations: zod
      .array(ServiceAssociation)
      .describe(
        "Links a service to one component that contributes to it. One row per (service, member) pair.",
      ),
    trading_hub_associations: zod
      .array(TradingHubAssociation)
      .default([])
      .describe(
        "Links a trading hub to one associated entity. Added after the other association arrays, so older documents omit it.",
      ),
    time_series_associations: zod
      .array(TimeSeriesAssociation)
      .describe(
        "Time series metadata rows, one per (series, owner) association. Values themselves never appear here.",
      ),
    // ext's key order is not preserved on round-trip: ECMAScript enumerates
    // integer-like keys in ascending numeric order regardless of insertion
    // order, and no JSON API recovers the original. See README, Known
    // limitations.
    ext: zod
      .record(zod.string(), genericRecord)
      .default({})
      .describe(
        "Source data no schema field claims, keyed by the stringified component id it belongs to.",
      ),
    time_series_storage_file: zod
      .string()
      .nullable()
      .describe(
        "Basename of the HDF5 sidecar holding time series values, or null when the system has no time series.",
      ),
  })
  .strict()
  .describe(
    "A whole serialized power system: components bucketed by type name, the association tables linking them, and the name of the HDF5 sidecar holding time series values. Mirrors `Core/SystemDocument.json`.",
  );

export type SystemDocument = zod.input<typeof SystemDocument>;
export type SystemDocumentOutput = zod.output<typeof SystemDocument>;

export const PortfolioDocument = zod
  .object({
    name: zod
      .string()
      .nullable()
      .optional()
      .describe("Optional portfolio name."),
    description: zod
      .string()
      .nullable()
      .optional()
      .describe("Optional free-text description of the portfolio."),
    data_source: zod
      .string()
      .nullable()
      .optional()
      .describe(
        "Optional identifier of the source the portfolio data was drawn from.",
      ),
    aggregation: zod
      .string()
      .describe(
        "Qualified type name of the regional aggregation the portfolio groups its regions by. A type identifier resolved by the consumer, not a component in the document.",
      ),
    financial_data: PortfolioFinancialData.optional().describe(
      "Portfolio-wide financial parameters: the base economic year every cost is discounted to a net present value in, and the discount, inflation, and interest rates used in that conversion. Absent when the portfolio carries no financial data.",
    ),
    components: zod
      .record(zod.string(), zod.array(genericRecord))
      .describe(
        'Components grouped by type name, e.g. `{"SupplyTechnology": [...], "StorageTechnology": [...]}`. Keys are the referenced schema\'s `title` and must be emitted in sorted order.',
      ),
    supplemental_attributes: zod
      .array(genericRecord)
      .describe(
        "Supplemental attributes in one flat array rather than bucketed by type; `supplemental_attribute_associations` carries the `attribute_type` discriminator a consumer needs to pick a converter. Examples: RetirementPotential, RetrofitPotential, ExistingDevices, TopologyMapping.",
      ),
    supplemental_attribute_associations: zod
      .array(SupplementalAttributeAssociation)
      .describe(
        "Links each supplemental attribute to the entity it describes. One row per (attribute, entity) pair.",
      ),
    requirements_associations: zod
      .array(RequirementAssociation)
      .describe(
        "Links each policy requirement to one member subject to it: `requirement_id` names the requirement and `entity_id` names the member. One row per (requirement, member) pair.",
      ),
    investment_schedule: genericRecord
      .nullable()
      .optional()
      .describe(
        "Optional investment decisions container: the schedule of capacity installations produced by solving the portfolio. A model output rather than an input, absent from an inputs-only portfolio, and carried opaquely.",
      ),
    time_series_associations: zod
      .array(TimeSeriesAssociation)
      .describe(
        "Time series metadata rows, one per (series, owner) association. Values themselves never appear here.",
      ),
    // Same integer-like key-order caveat as SystemDocument.ext; see the
    // comment there.
    ext: zod
      .record(zod.string(), genericRecord)
      .default({})
      .describe(
        "Source data no schema field claims, keyed by the stringified component id it belongs to.",
      ),
    base_system_file: zod
      .string()
      .nullable()
      .describe(
        "Basename of the sidecar holding the base power system this portfolio expands, serialized as its own system document, or null when the portfolio has no base system.",
      ),
    time_series_storage_file: zod
      .string()
      .nullable()
      .describe(
        "Basename of the HDF5 sidecar holding time series values, or null when the portfolio has no time series.",
      ),
  })
  .strict()
  .describe(
    "A whole serialized investment portfolio: the candidate technologies, regional aggregations, and policy requirements that make up an expansion problem, the supplemental attributes describing them, the association tables linking them, and the names of the sidecar files holding the base power system and the time series values. Mirrors `Investments/PortfolioDocument.json`.",
  );

export type PortfolioDocument = zod.input<typeof PortfolioDocument>;
export type PortfolioDocumentOutput = zod.output<typeof PortfolioDocument>;

// --- Byte-identical round-tripping -----------------------------------------
//
// JavaScript has one Number type, so a plain `JSON.parse` -> `JSON.stringify`
// round trip silently collapses a whole-valued float (`138.0`) to an integer
// literal (`138`) — Python's write_document doesn't do this because Python
// keeps float and int as distinct types. The fix is Node 22+'s JSON source
// preservation: `JSON.parse`'s reviver receives a `context.source` string
// carrying the exact literal text of the value being revived, and
// `JSON.rawJSON(text)` creates a value `JSON.stringify` emits verbatim. Every
// number is revived this way, keyed by its own original source text, so
// `138.0` stays `138.0` and plain integers are unaffected.
//
// This repo's installed TypeScript does not yet ship type declarations for
// either API (both are very recent V8/Node additions), so they are declared
// locally rather than by widening the project's `lib`.
declare global {
  interface JSON {
    rawJSON(value: string): unknown;
    isRawJSON(value: unknown): boolean;
  }
}

interface ReviverContext {
  source?: string;
}

type ReviverWithContext = (
  this: unknown,
  key: string,
  value: unknown,
  context: ReviverContext,
) => unknown;

const parseWithContext = JSON.parse as (
  text: string,
  reviver: ReviverWithContext,
) => unknown;

const REQUIRED_NODE_VERSION_MESSAGE =
  "power-openapi-models: byte-identical SystemDocument round-tripping requires " +
  "Node.js >=22 (JSON.rawJSON and JSON.parse's reviver `context.source`). " +
  `Detected runtime: ${typeof process === "object" ? process.version : "unknown"}.`;

/**
 * Throws with a clear, actionable message if the running Node.js lacks the
 * raw-number-preservation APIs `readDocument`/`writeDocument` depend on.
 * Deliberately a hard error, never a silent fallback to lossy number
 * formatting: a document that quietly stopped round-tripping on an older
 * runtime is exactly the class of bug this module exists to avoid.
 */
function assertRawNumberSupport(): void {
  if (typeof JSON.rawJSON !== "function") {
    throw new Error(REQUIRED_NODE_VERSION_MESSAGE);
  }
  let sawSource = false;
  parseWithContext("0", (_key, _value, context) => {
    if (context && typeof context.source === "string") {
      sawSource = true;
    }
    return _value;
  });
  if (!sawSource) {
    throw new Error(REQUIRED_NODE_VERSION_MESSAGE);
  }
}

function reviveRawNumbers(
  _key: string,
  value: unknown,
  context: ReviverContext,
): unknown {
  if (typeof value === "number" && typeof context.source === "string") {
    return JSON.rawJSON(context.source);
  }
  return value;
}

function sortKeys<T extends Record<string, unknown>>(obj: T): T {
  const sorted = {} as Record<string, unknown>;
  for (const key of Object.keys(obj).sort()) {
    sorted[key] = obj[key];
  }
  return sorted as T;
}

const RAW_NUMBER_TREE = Symbol("power-openapi-models:rawNumberTree");

/**
 * Read and validate one document, preserving numeric literals.
 *
 * Shared by both container types: the raw-number machinery above is about
 * JSON, not about which document is being read, so parameterizing on the zod
 * schema keeps one implementation rather than two that can drift.
 *
 * Validates the parsed JSON against `schema` (throwing on invalid input, the
 * same as Python's `model_validate_json`) and returns a value that reads like
 * ordinary parsed JSON (numbers are plain `number`s) but secretly carries,
 * alongside it, the exact source text of every number it contained. `write`
 * uses that to reproduce the original numeric literals exactly; nothing else
 * about the returned object's shape depends on it.
 */
function read<T>(schema: { parse(value: unknown): unknown }, path: string): T {
  assertRawNumberSupport();
  const text = readFileSync(path, "utf-8");
  const raw: unknown = JSON.parse(text);
  schema.parse(raw);
  const rawNumberTree = parseWithContext(text, reviveRawNumbers);
  Object.defineProperty(raw as object, RAW_NUMBER_TREE, {
    value: rawNumberTree,
    enumerable: false,
    configurable: true,
  });
  return raw as T;
}

/**
 * Read a `SystemDocument` from a JSON file.
 */
export function readDocument(path: string): SystemDocumentOutput {
  return read<SystemDocumentOutput>(SystemDocument, path);
}

/**
 * Read a `PortfolioDocument` from a JSON file.
 */
export function readPortfolioDocument(path: string): PortfolioDocumentOutput {
  return read<PortfolioDocumentOutput>(PortfolioDocument, path);
}

/**
 * Write one document to `path` as JSON, matching Python's `write_document` /
 * `write_portfolio_document`: both `components` and the top-level object have
 * their keys sorted, a field the input never carried is not materialized into
 * the output, and the file ends with a trailing newline. When `doc` came from
 * the matching reader, the exact original numeric literals (e.g. `138.0`
 * rather than `138`) are reproduced as well; a `doc` built by hand has no
 * original source text to draw on, so its numbers serialize with ordinary
 * `JSON.stringify` formatting.
 */
function write(
  schema: { parse(value: unknown): unknown },
  doc: unknown,
  path: string,
): void {
  assertRawNumberSupport();
  schema.parse(doc);

  const rawNumberTree = (doc as Record<PropertyKey, unknown>)[
    RAW_NUMBER_TREE
  ] as Record<string, unknown> | undefined;
  const source = (rawNumberTree ?? doc) as Record<string, unknown>;

  const sortedComponents = sortKeys(
    source.components as Record<string, unknown>,
  );
  const data = sortKeys({ ...source, components: sortedComponents });

  writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
}

/**
 * Write a `SystemDocument` to `path` as JSON.
 */
export function writeDocument(doc: SystemDocument, path: string): void {
  write(SystemDocument, doc, path);
}

/**
 * Write a `PortfolioDocument` to `path` as JSON.
 */
export function writePortfolioDocument(
  doc: PortfolioDocument,
  path: string,
): void {
  write(PortfolioDocument, doc, path);
}

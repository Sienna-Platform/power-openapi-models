/**
 * Hand-written (NOT generated): the schema-version reader rule.
 *
 * Implements `docs/VERSIONING.md` in SiennaSchemas; `scripts/schema_version.py`
 * there is the reference and `tests/fixtures/versioning/cases.json` the shared
 * vectors. Counterpart of `power_openapi_models/_versioning.py`.
 */

declare const __SCHEMA_VERSION__: string;

/** The schema version this package was built from (no leading `v`). */
export const SCHEMA_VERSION: string = __SCHEMA_VERSION__;

export type SchemaVersionOutcome =
  "missing" | "malformed" | "incompatible" | "newer" | "upgradable" | "current";

const PATTERN =
  /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?$/;

interface Parsed {
  triple: [bigint, bigint, bigint];
  pre: string | null;
}

function parse(s: unknown): Parsed | null {
  const m = typeof s === "string" ? PATTERN.exec(s) : null;
  if (m === null) {
    return null;
  }
  return {
    triple: [BigInt(m[1]), BigInt(m[2]), BigInt(m[3])],
    pre: m[4] === undefined ? null : m[4].slice(1),
  };
}

function lineName(v: Parsed): string {
  return v.triple[0] === 0n ? `0.${v.triple[1]}` : String(v.triple[0]);
}

function compareTriples(a: Parsed, b: Parsed): number {
  for (let i = 0; i < 3; i += 1) {
    if (a.triple[i] !== b.triple[i]) {
      return a.triple[i] < b.triple[i] ? -1 : 1;
    }
  }
  return 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The reader rule on the raw parsed JSON, against an explicit reader version.
 * Pure; throws `TypeError` on a non-object root (the public `checkSchemaVersion`
 * in document.ts reports that as the schema's format error instead).
 */
export function classifySchemaVersion(
  reader: string,
  raw: unknown,
): SchemaVersionOutcome {
  if (!isRecord(raw)) {
    throw new TypeError("document must be a JSON object");
  }
  if (!("schema_version" in raw)) {
    return "missing";
  }
  const dv = parse(raw.schema_version);
  if (dv === null) {
    return "malformed";
  }
  const rv = parse(reader);
  if (rv === null) {
    throw new Error(
      `reader schema version ${JSON.stringify(reader)} is not a valid version`,
    );
  }
  const samePre = dv.pre === rv.pre;
  const sameTriple = compareTriples(dv, rv) === 0;
  if ((dv.pre !== null || rv.pre !== null) && !(samePre && sameTriple)) {
    return "incompatible";
  }
  if (lineName(dv) !== lineName(rv)) {
    return "incompatible";
  }
  const cmp = compareTriples(dv, rv);
  if (cmp > 0) {
    return "newer";
  }
  return cmp < 0 ? "upgradable" : "current";
}

/** Canonical error text for an outcome other than `upgradable` / `current`. */
function message(
  outcome: SchemaVersionOutcome,
  reader: string,
  documentVersion: unknown,
): string {
  const d = documentVersion;
  const dv = parse(d);
  const rv = parse(reader);
  switch (outcome) {
    case "missing":
      return (
        "document has no schema_version: it predates versioning; re-export it with a " +
        "current producer (psy5 bundles: PowerSystemsUpdater)"
      );
    case "malformed":
      return `document schema_version ${JSON.stringify(d)} is not a valid version`;
    case "incompatible":
      if (dv === null || rv === null || dv.pre !== null || rv.pre !== null) {
        return (
          `document written by schema ${String(d)} cannot be read by schema ${reader}: ` +
          "dev builds read only their own output"
        );
      }
      return (
        `document written by schema ${String(d)} (line ${lineName(dv)}) cannot be read by schema ` +
        `${reader} (line ${lineName(rv)}): documents do not cross compatibility lines; ` +
        "migrating between lines is a separate upgrade tool's job " +
        "(psy5 bundles: PowerSystemsUpdater)"
      );
    case "newer":
      return (
        `document written by schema ${String(d)}; this reader understands up to ${reader}; ` +
        `update the model package to one built from >= ${String(d)}`
      );
    default:
      throw new Error(`outcome ${outcome} is not an error`);
  }
}

export class SchemaVersionError extends Error {
  readonly outcome: SchemaVersionOutcome;
  readonly readerVersion: string;
  /** The raw `schema_version` value; `undefined` when the document has none. */
  readonly documentVersion: unknown;

  constructor(
    outcome: SchemaVersionOutcome,
    readerVersion: string,
    documentVersion: unknown,
  ) {
    super(message(outcome, readerVersion, documentVersion));
    this.name = "SchemaVersionError";
    this.outcome = outcome;
    this.readerVersion = readerVersion;
    this.documentVersion = documentVersion;
  }
}

/**
 * Throws `SchemaVersionError` unless `raw` is `upgradable` or `current`;
 * returns the document's version otherwise.
 */
export function assertReadable(reader: string, raw: unknown): string {
  const outcome = classifySchemaVersion(reader, raw);
  if (outcome !== "upgradable" && outcome !== "current") {
    const d = isRecord(raw) ? raw.schema_version : undefined;
    throw new SchemaVersionError(outcome, reader, d);
  }
  return (raw as { schema_version: string }).schema_version;
}

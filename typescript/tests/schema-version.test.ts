/**
 * Schema-version reader rule, stamping, source writes and canonical encoding
 * (src/schema_version.ts, src/document.ts).
 *
 * The shared vectors and fixtures come from the SiennaSchemas checkout, found
 * the same way portfolio-document.test.ts finds the schemas.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";
import { ZodError } from "zod";

import {
  type ReadOptions,
  type WriteOptions,
  SCHEMA_VERSION,
  SchemaVersionError,
  type SchemaVersionOutcome,
  checkSchemaVersion,
  getSourceSchemaVersion,
  readDocument,
  readPortfolioDocument,
  upgradeDocument,
  upgradePortfolioDocument,
  writeDocument,
  writePortfolioDocument,
} from "../src/document";
import type { PortfolioFinancialData } from "../src/investments/models";
import { classifySchemaVersion } from "../src/schema_version";

const SCHEMAS_DIR =
  process.env.SIENNA_SCHEMAS_DIR ??
  join(__dirname, "..", "..", "..", "SiennaSchemas");
const VERSIONING = join(SCHEMAS_DIR, "tests", "fixtures", "versioning");
const SYSTEM_FIXTURE = join(VERSIONING, "system_document.json");
const PORTFOLIO_FIXTURE = join(VERSIONING, "portfolio_document.json");

// Fixtures are stamped D; the reader override plays a later release.
const D = "0.2.0";
const R = "0.2.1";

const tmp = mkdtempSync(join(tmpdir(), "schema-version-"));
const bundlesDir = join(tmp, "bundles");

function jsonFile(name: string, value: unknown): string {
  const path = join(tmp, name);
  writeFileSync(path, JSON.stringify(value));
  return path;
}

function loadJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, "utf-8")) as Record<string, unknown>;
}

beforeAll(() => {
  execFileSync("python3", [
    join(SCHEMAS_DIR, "scripts", "build_bundles.py"),
    "--root",
    SCHEMAS_DIR,
    "--version",
    D,
    "--out",
    bundlesDir,
  ]);
});

describe("shared reader-rule vectors", () => {
  const cases = loadJson(join(VERSIONING, "cases.json")).cases as {
    reader: string;
    document: unknown;
    outcome: string;
    expected_message?: string;
  }[];

  it("has vectors", () => {
    expect(cases.length).toBeGreaterThan(10);
  });

  it.each(cases.map((c, i) => [i, c] as const))("vector %i", (_i, c) => {
    expect(classifySchemaVersion(c.reader, c.document)).toBe(c.outcome);
    if (c.expected_message !== undefined) {
      const stamp = (c.document as Record<string, unknown>).schema_version;
      expect(
        new SchemaVersionError(
          c.outcome as SchemaVersionOutcome,
          c.reader,
          stamp,
        ).message,
      ).toBe(c.expected_message);
    }
  });

  it("checkSchemaVersion uses this package's version", () => {
    expect(checkSchemaVersion({ schema_version: SCHEMA_VERSION })).toBe(
      "current",
    );
  });
});

type ReadFn = (path: string, options?: ReadOptions) => object;
type WriteFn = (doc: never, path: string, options?: WriteOptions) => void;

const kinds: [string, string, ReadFn, WriteFn][] = [
  ["SystemDocument", SYSTEM_FIXTURE, readDocument, writeDocument],
  [
    "PortfolioDocument",
    PORTFOLIO_FIXTURE,
    readPortfolioDocument,
    writePortfolioDocument,
  ],
];

describe.each(kinds)("%s", (_name, fixture, read, writeDoc) => {
  const write = (doc: object, path: string, options?: WriteOptions) =>
    writeDoc(doc as never, path, options);
  const base = loadJson(fixture);

  it.each([
    [
      "absent",
      (d: Record<string, unknown>) => {
        delete d.schema_version;
      },
      "missing",
      "has no schema_version",
    ],
    [
      "newer",
      (d: Record<string, unknown>) => {
        d.schema_version = "0.2.9";
      },
      "newer",
      "this reader understands up to 0.2.1",
    ],
    [
      "incompatible",
      (d: Record<string, unknown>) => {
        d.schema_version = "0.1.0";
      },
      "incompatible",
      "line 0.1",
    ],
    [
      "malformed",
      (d: Record<string, unknown>) => {
        d.schema_version = "v0.2.0";
      },
      "malformed",
      '"v0.2.0" is not a valid version',
    ],
  ])(
    "rejects %s stamp before strict decoding",
    (label, edit, outcome, text) => {
      const doc = structuredClone(base);
      edit(doc);
      doc.surprise_key = 1;
      const path = jsonFile(`${label}.json`, doc);
      let caught: unknown;
      try {
        read(path, { readerVersion: R });
      } catch (e) {
        caught = e;
      }
      expect(caught).toBeInstanceOf(SchemaVersionError);
      const err = caught as SchemaVersionError;
      expect(err.outcome).toBe(outcome);
      expect(err.readerVersion).toBe(R);
      expect(err.message).toContain(text);
    },
  );

  it("records the document's version and stamps the reader's on write", () => {
    const doc = read(fixture, { readerVersion: R });
    expect(getSourceSchemaVersion(doc)).toBe(D);
    const out = join(tmp, `${_name}-current.json`);
    write(doc, out, { readerVersion: R });
    const text = readFileSync(out, "utf-8");
    expect(Object.keys(JSON.parse(text))[0]).toBe("schema_version");
    expect(loadJson(out).schema_version).toBe(R);
    expect(Object.keys(doc)).toContain("schema_version");
    expect(JSON.stringify(doc)).not.toContain("source_schema_version");
  });

  it("source write keeps D when the document uses nothing newer", () => {
    const doc = read(fixture, { readerVersion: R });
    const out = join(tmp, `${_name}-source.json`);
    write(doc, out, { schemaVersion: "source", readerVersion: R, bundlesDir });
    expect(loadJson(out).schema_version).toBe(D);
  });

  it("source write lists every offending path", () => {
    const edited = structuredClone(base);
    const components = edited.components as Record<
      string,
      Record<string, unknown>[]
    >;
    const [type] = Object.keys(components);
    components[type][0].bogus_one = 1;
    components[type][0].bogus_two = 2;
    const doc = read(jsonFile(`${_name}-bogus.json`, edited), {
      readerVersion: R,
    });
    const out = join(tmp, `${_name}-bogus-out.json`);
    expect(() =>
      write(doc, out, {
        schemaVersion: "source",
        readerVersion: R,
        bundlesDir,
      }),
    ).toThrow(
      new RegExp(
        `/components/${type}/0/bogus_one[\\s\\S]*/components/${type}/0/bogus_two[\\s\\S]*"current"`,
      ),
    );
  });

  it("source write without a bundle names the expected path", () => {
    const doc = read(fixture, { readerVersion: R });
    expect(() =>
      write(doc, join(tmp, "nobundle.json"), {
        schemaVersion: "source",
        readerVersion: R,
        bundlesDir: join(tmp, "empty"),
      }),
    ).toThrow(join(tmp, "empty", D, `${_name}.json`));
  });

  it("source write without the validator names ajv", () => {
    const doc = read(fixture, { readerVersion: R });
    expect(() =>
      write(doc, join(tmp, "noajv.json"), {
        schemaVersion: "source",
        readerVersion: R,
        bundlesDir,
        ajv: "ajv-not-installed",
      }),
    ).toThrow(/"ajv-not-installed"/);
  });

  it("source write of a current document needs no validator", () => {
    const doc = read(fixture, { readerVersion: D });
    const out = join(tmp, `${_name}-same.json`);
    write(doc, out, {
      schemaVersion: "source",
      readerVersion: D,
      ajv: "ajv-not-installed",
    });
    expect(loadJson(out).schema_version).toBe(D);
  });

  it("source write of a spread copy keeps D", () => {
    const doc = read(fixture, { readerVersion: R });
    const copy = { ...doc, name: "edited" };
    expect(getSourceSchemaVersion(copy)).toBe(D);
    const out = join(tmp, `${_name}-copy.json`);
    write(copy, out, { schemaVersion: "source", readerVersion: R, bundlesDir });
    expect(loadJson(out).schema_version).toBe(D);
  });

  it("source write rejects a hand-built newer stamp", () => {
    const doc = {
      ...read(fixture, { readerVersion: R }),
      schema_version: "99.0.0",
    };
    expect(() =>
      write(doc, join(tmp, "newer-stamp.json"), {
        schemaVersion: "source",
        readerVersion: R,
        bundlesDir,
      }),
    ).toThrow(SchemaVersionError);
  });
});

describe("non-object root", () => {
  it.each(["[]", "3", "null", '"x"'])(
    "is a format error, not a missing stamp: %s",
    (text) => {
      const path = join(tmp, "root.json");
      writeFileSync(path, text);
      for (const read of [readDocument, readPortfolioDocument]) {
        expect(() => read(path)).toThrow();
        expect(() => read(path)).not.toThrow(SchemaVersionError);
      }
      expect(() => checkSchemaVersion(JSON.parse(text))).toThrow(ZodError);
      expect(() => checkSchemaVersion(JSON.parse(text))).not.toThrow(
        SchemaVersionError,
      );
    },
  );
});

describe("upgrade", () => {
  it("upgrades a system document to the reader's version", () => {
    const dst = join(tmp, "up-system.json");
    upgradeDocument(SYSTEM_FIXTURE, dst, { readerVersion: R });
    expect(loadJson(dst).schema_version).toBe(R);
    expect(() =>
      upgradeDocument(SYSTEM_FIXTURE, dst, { readerVersion: R }),
    ).toThrow(/force/);
    upgradeDocument(SYSTEM_FIXTURE, dst, { readerVersion: R, force: true });
  });

  it("upgrades a portfolio document to the reader's version", () => {
    const dst = join(tmp, "up-portfolio.json");
    upgradePortfolioDocument(PORTFOLIO_FIXTURE, dst, { readerVersion: R });
    expect(loadJson(dst).schema_version).toBe(R);
  });
});

describe("canonical encoding", () => {
  const system = {
    schema_version: SCHEMA_VERSION,
    name: null,
    components: {},
    supplemental_attributes: [],
    supplemental_attribute_associations: [],
    plant_associations: [],
    combined_cycle_associations: [],
    service_associations: [],
    trading_hub_associations: [],
    time_series_associations: [],
    time_series_storage_file: null,
  };

  it("omits null and default-equal optionals but keeps required nullables", () => {
    const out = join(tmp, "canonical-system.json");
    writeDocument(system, out);
    const written = loadJson(out);
    expect("trading_hub_associations" in written).toBe(false);
    expect("name" in written).toBe(false);
    expect(written.time_series_storage_file).toBeNull();
  });

  it("keeps a non-default optional", () => {
    const out = join(tmp, "canonical-system-kept.json");
    writeDocument({ ...system, frequency: 60 }, out);
    expect(loadJson(out).frequency).toBe(60);
  });

  it("omits null optionals of a portfolio", () => {
    const portfolio = {
      schema_version: SCHEMA_VERSION,
      aggregation: "Area",
      description: null,
      investment_schedule: null,
      components: {},
      supplemental_attributes: [],
      supplemental_attribute_associations: [],
      requirements_associations: [],
      time_series_associations: [],
      base_system_file: null,
      time_series_storage_file: null,
    };
    const out = join(tmp, "canonical-portfolio.json");
    writePortfolioDocument(portfolio, out);
    const written = loadJson(out);
    expect("description" in written).toBe(false);
    expect("investment_schedule" in written).toBe(false);
    expect(written.base_system_file).toBeNull();
  });

  const portfolioWithRates = (financial_data: PortfolioFinancialData) => ({
    schema_version: SCHEMA_VERSION,
    aggregation: "Area",
    financial_data,
    components: {},
    supplemental_attributes: [],
    supplemental_attribute_associations: [],
    requirements_associations: [],
    time_series_associations: [],
    base_system_file: null,
    time_series_storage_file: null,
  });

  it("always writes the three required financial rates", () => {
    const out = join(tmp, "canonical-rates.json");
    writePortfolioDocument(
      portfolioWithRates({
        id: 5,
        base_year: 2020,
        discount_rate: 0,
        interest_rate: 0.123,
      } as PortfolioFinancialData),
      out,
    );
    expect(loadJson(out).financial_data).toEqual({
      id: 5,
      base_year: 2020,
      discount_rate: 0,
      inflation_rate: 0,
      interest_rate: 0.123,
    });
  });

  it("writes a current stamp over a junk one", () => {
    const out = join(tmp, "junk-stamp.json");
    writeDocument({ ...system, schema_version: "junk" }, out);
    expect(loadJson(out).schema_version).toBe(SCHEMA_VERSION);
  });
});

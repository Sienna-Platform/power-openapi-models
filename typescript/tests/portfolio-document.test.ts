/**
 * Tests for the hand-written PortfolioDocument container (src/document.ts).
 *
 * Mirrors python/tests/test_document.py's PortfolioDocument tests: the field
 * set and required list are checked against Investments/PortfolioDocument.json
 * in SiennaSchemas, so the container cannot drift from the schema it mirrors.
 */

import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  SCHEMA_VERSION,
  PortfolioDocument,
  readPortfolioDocument,
  writePortfolioDocument,
} from "../src/document";

const SCHEMAS_DIR =
  process.env.SIENNA_SCHEMAS_DIR ??
  join(__dirname, "..", "..", "..", "SiennaSchemas");
const SCHEMA_PATH = join(SCHEMAS_DIR, "Investments", "PortfolioDocument.json");

interface JsonSchema {
  properties: Record<string, unknown>;
  required: string[];
}

function loadSchema(): JsonSchema {
  return JSON.parse(readFileSync(SCHEMA_PATH, "utf-8")) as JsonSchema;
}

const minimal = {
  schema_version: SCHEMA_VERSION,
  aggregation: "Area",
  components: {},
  supplemental_attributes: [],
  supplemental_attribute_associations: [],
  requirements_associations: [],
  time_series_associations: [],
  base_system_file: null,
  time_series_storage_file: null,
};

describe("PortfolioDocument", () => {
  it("field set matches the schema's properties", () => {
    const schema = loadSchema();
    const fields = Object.keys(PortfolioDocument.shape).sort();
    expect(fields).toEqual(Object.keys(schema.properties).sort());
  });

  it("required fields match the schema's required list", () => {
    const schema = loadSchema();
    const required = Object.entries(PortfolioDocument.shape)
      .filter(
        ([, field]) =>
          !(field as { safeParse(v: unknown): { success: boolean } }).safeParse(
            undefined,
          ).success,
      )
      .map(([name]) => name)
      .sort();
    expect(required).toEqual([...schema.required].sort());
  });

  it("accepts a minimal portfolio", () => {
    expect(() => PortfolioDocument.parse(minimal)).not.toThrow();
  });

  it("rejects an unknown top-level key", () => {
    // The undeclared `requirements` key a producer might reach for belongs in
    // `requirements_associations`; the container must reject it, not carry it.
    expect(() =>
      PortfolioDocument.parse({ ...minimal, requirements: [] }),
    ).toThrow();
  });

  it("round-trips through write and read", () => {
    const doc = {
      ...minimal,
      name: "minimal portfolio",
      components: {
        SupplyTechnology: [{ id: 1, name: "wind" }],
        CarbonCaps: [{ id: 2, name: "cap 2030" }],
      },
      supplemental_attributes: [{ id: 3, buses: ["bus1"] }],
      supplemental_attribute_associations: [
        {
          component_id: 1,
          component_type: "SupplyTechnology",
          attribute_id: 3,
          attribute_type: "TopologyMapping",
        },
      ],
      requirements_associations: [{ requirement_id: 2, entity_id: 1 }],
      base_system_file: "base_system.json",
    };

    const dir = mkdtempSync(join(tmpdir(), "portfolio-"));
    const path = join(dir, "portfolio.json");
    writePortfolioDocument(doc, path);
    const reloaded = readPortfolioDocument(path);

    expect(reloaded).toEqual(doc);
  });

  it("sorts component keys and ends with a newline", () => {
    const doc = {
      ...minimal,
      components: {
        StorageTechnology: [{ id: 2 }],
        CarbonCaps: [{ id: 1 }],
      },
    };
    const dir = mkdtempSync(join(tmpdir(), "portfolio-"));
    const path = join(dir, "portfolio.json");
    writePortfolioDocument(doc, path);

    const text = readFileSync(path, "utf-8");
    expect(text.endsWith("\n")).toBe(true);
    const written = JSON.parse(text) as { components: Record<string, unknown> };
    expect(Object.keys(written.components)).toEqual([
      "CarbonCaps",
      "StorageTechnology",
    ]);
  });
});

import { describe, expect, it } from "vitest";

import * as root from "../src/index";
import * as infrastructureCore from "../src/infrastructure_core";
import * as core from "../src/core";
import * as operations from "../src/operations";
import * as investments from "../src/investments";
import * as dynamics from "../src/dynamics";
import * as timeseries from "../src/timeseries";
import * as document from "../src/document";

describe("subpath exports", () => {
  it("infrastructure_core yields a usable zod schema", () => {
    expect(typeof infrastructureCore.SupplementalAttributeAssociation.parse).toBe("function");
  });

  it("core yields a usable zod schema", () => {
    expect(typeof core.ACBus.parse).toBe("function");
  });

  it("operations yields a usable zod schema", () => {
    expect(typeof operations.PlantAssociation.parse).toBe("function");
  });

  it("investments yields a usable zod schema", () => {
    expect(Object.keys(investments).length).toBeGreaterThan(0);
  });

  it("dynamics yields a usable zod schema", () => {
    expect(Object.keys(dynamics).length).toBeGreaterThan(0);
  });

  it("timeseries yields a usable zod schema", () => {
    expect(typeof timeseries.TimeSeriesAssociation.parse).toBe("function");
  });

  it("document yields a usable zod schema plus readDocument/writeDocument", () => {
    expect(typeof document.SystemDocument.parse).toBe("function");
    expect(typeof document.readDocument).toBe("function");
    expect(typeof document.writeDocument).toBe("function");
  });

  it("the root index re-exports every domain as a namespace", () => {
    expect(typeof root.core.ACBus.parse).toBe("function");
    expect(typeof root.infrastructureCore.SupplementalAttributeAssociation.parse).toBe(
      "function",
    );
    expect(typeof root.operations.PlantAssociation.parse).toBe("function");
    expect(typeof root.timeseries.TimeSeriesAssociation.parse).toBe("function");
    expect(typeof root.document.SystemDocument.parse).toBe("function");
    expect(Object.keys(root.investments).length).toBeGreaterThan(0);
    expect(Object.keys(root.dynamics).length).toBeGreaterThan(0);
  });
});

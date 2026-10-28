import { describe, expect, it } from "vitest";

import { SeriesCompensator } from "../src/operations";
import { SingleTimeSeries, TimeSeriesAssociation } from "../src/timeseries";

// A model rejects a property its schema does not list, as the strict bundles and
// the Python and Rust packages do. A map schema stays open.
const series = (extra: Record<string, unknown> = {}) => ({
  association_id: 1,
  owner_id: 2,
  owner_type: "ACBus",
  owner_category: "Component",
  time_series_type: "SingleTimeSeries",
  name: "max_active_power",
  features: { scenario: "high", model_year: 2030 },
  uri: "abc123",
  element_type: "f64",
  element_shape: [],
  initial_timestamp: "2024-01-01T00:00:00Z",
  resolution: "PT1H",
  length: 24,
  ...extra,
});

describe("unknown properties", () => {
  it("are rejected by a model", () => {
    const result = SingleTimeSeries.safeParse(series({ owner_typ: "Typo" }));
    expect(result.success).toBe(false);
    expect(JSON.stringify(result.error?.issues)).toContain("owner_typ");
  });

  it("are rejected inside a union", () => {
    expect(
      TimeSeriesAssociation.safeParse(series({ owner_typ: "Typo" })).success,
    ).toBe(false);
  });

  // A schema with `if`/`then` rules renders as an `allOf`; zod's intersection with
  // the `unknown()` placeholder let an undeclared key through (dropUnknownIntersections).
  it("are rejected by a model with validation rules", () => {
    const result = SeriesCompensator.safeParse({ bogus_field: 1 });
    expect(JSON.stringify(result.error?.issues)).toContain("bogus_field");
  });

  it("are accepted by a map schema", () => {
    const parsed = SingleTimeSeries.parse(series());
    expect(Object.keys(parsed.features)).toEqual(["scenario", "model_year"]);
  });
});

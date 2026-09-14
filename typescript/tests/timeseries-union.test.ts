import { describe, expect, it } from "vitest";

import { TimeSeriesAssociation } from "../src/timeseries";

describe("TimeSeriesAssociation discriminated union", () => {
  it("parses a SingleTimeSeries member to the right variant", () => {
    const single = {
      association_id: 1,
      owner_id: 2,
      owner_type: "ACBus",
      owner_category: "Component",
      time_series_type: "SingleTimeSeries",
      name: "max_active_power",
      features: {},
      uri: "abc123",
      element_type: "f64",
      element_shape: [],
      initial_timestamp: "2024-01-01T00:00:00Z",
      resolution: "PT1H",
      length: 24,
    };

    const parsed = TimeSeriesAssociation.parse(single);
    expect(parsed.time_series_type).toBe("SingleTimeSeries");
  });

  it("parses a Scenarios member to the right variant", () => {
    const scenarios = {
      association_id: 5,
      owner_id: 6,
      owner_type: "ThermalStandard",
      owner_category: "Component",
      time_series_type: "Scenarios",
      name: "forecast",
      features: {},
      uri: "def456",
      element_type: "f64",
      element_shape: [],
      initial_timestamp: "2024-01-01T00:00:00Z",
      resolution: "PT1H",
      horizon: "P1D",
      interval: "PT1H",
      count: 10,
      scenario_count: 3,
    };

    const parsed = TimeSeriesAssociation.parse(scenarios);
    expect(parsed.time_series_type).toBe("Scenarios");
  });

  it("rejects a member matching no branch", () => {
    const invalid = {
      association_id: 1,
      owner_id: 2,
      owner_type: "ACBus",
      owner_category: "Component",
      time_series_type: "NotARealType",
      name: "max_active_power",
    };

    expect(() => TimeSeriesAssociation.parse(invalid)).toThrow();
  });
});

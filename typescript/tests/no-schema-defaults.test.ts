import { describe, expect, it } from "vitest";

import { SingleTimeSeries } from "../src/timeseries/models";

// No SDK fills a schema `default` (see the README): an omitted optional field stays
// absent. A `const` field, such as a discriminator, keeps its fixed value.
describe("schema defaults", () => {
  it("leave an omitted optional field absent", () => {
    const parsed = SingleTimeSeries.parse({
      association_id: 1,
      owner_id: 2,
      owner_type: "ACBus",
      owner_category: "Component",
      name: "max_active_power",
      features: {},
      uri: "abc123",
      element_type: "f64",
      element_shape: [],
      initial_timestamp: "2024-01-01T00:00:00Z",
      resolution: "PT1H",
      length: 24,
    });
    expect(parsed.interval_alignment).toBeUndefined();
    expect(parsed.time_series_type).toBe("SingleTimeSeries");
  });
});

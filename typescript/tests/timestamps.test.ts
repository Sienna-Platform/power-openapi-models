import { describe, expect, it } from "vitest";

import { DataSource } from "../src/infrastructure_core/models";
import { SingleTimeSeries } from "../src/timeseries/models";

// `format: date-time` fields accept a timestamp with no offset, as the Python and
// Rust packages do (both read it as UTC). zod only validates, so the string is
// returned as written. See codegen/typescript/postprocess.ts (fixNaiveTimestamps).

const series = (initial_timestamp: string) => ({
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
  initial_timestamp,
  resolution: "PT1H",
  length: 24,
});

describe("date-time fields", () => {
  it.each([
    "2024-01-01T00:00:00",
    "2024-01-01T00:00:00.250",
    "2024-01-01T00:00:00Z",
    "2024-01-01T02:00:00+02:00",
  ])("accepts %s", (ts) => {
    expect(SingleTimeSeries.parse(series(ts)).initial_timestamp).toBe(ts);
  });

  it.each(["2024-01-01", "not a timestamp", "", "2024-13-01T00:00:00"])(
    "still rejects %j",
    (ts) => {
      expect(SingleTimeSeries.safeParse(series(ts)).success).toBe(false);
    },
  );

  it("applies to the nullable field too", () => {
    const base = { id: 1, fields: [], retrieved_at: "2024-01-01T00:00:00" };
    expect(
      DataSource.safeParse({ ...base, published_at: "2024-02-01T00:00:00" })
        .success,
    ).toBe(true);
    expect(DataSource.safeParse({ ...base, published_at: null }).success).toBe(
      true,
    );
  });
});

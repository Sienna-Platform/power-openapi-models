import { describe, expect, it } from "vitest";

import { SCHEMA_VERSION } from "../src/document";
import { DataSource } from "../src/infrastructure_core/models";
import { SingleTimeSeries } from "../src/timeseries/models";

// `format: date-time` needs `Z` or a UTC offset; `format: date-time-local` has none.
// zod only validates, so a valid string is returned exactly as written.

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

const [major, minor] = SCHEMA_VERSION.split(".").map(Number);
const hasLocalSeriesTimestamps = major > 0 || minor >= 4;

describe("date-time fields", () => {
  it.each(["2024-01-01T00:00:00Z", "2024-01-01T02:00:00+02:00"])(
    "accepts %s",
    (ts) => {
      expect(SingleTimeSeries.parse(series(ts)).initial_timestamp).toBe(ts);
    },
  );

  it.each([
    "2024-01-01",
    "not a timestamp",
    "",
    "2024-13-01T00:00:00Z",
    "2024-01-01 00:00:00Z",
    "2024-01-01t00:00:00z",
    "2024-01-01T00:00Z",
    "2024-01-01T00:00:00+0200",
    "2024-01-01T00:00:00Z\n",
  ])("rejects %j", (ts) => {
    expect(SingleTimeSeries.safeParse(series(ts)).success).toBe(false);
  });

  it("needs an offset on a data source", () => {
    const base = { id: 1, fields: [], retrieved_at: "2024-01-01T00:00:00Z" };
    expect(DataSource.safeParse({ ...base, published_at: null }).success).toBe(
      true,
    );
    expect(
      DataSource.safeParse({ ...base, retrieved_at: "2024-01-01T00:00:00" })
        .success,
    ).toBe(false);
    expect(
      DataSource.safeParse({ ...base, published_at: "2024-02-01T00:00:00" })
        .success,
    ).toBe(false);
  });
});

describe.runIf(hasLocalSeriesTimestamps)(
  "date-time-local series timestamps",
  () => {
    it.each(["2024-01-01T00:00:00", "2024-01-01T00:00:00.250"])(
      "accepts %s as written",
      (ts) => {
        expect(SingleTimeSeries.parse(series(ts)).initial_timestamp).toBe(ts);
      },
    );

    it("rejects more than three fractional digits", () => {
      expect(
        SingleTimeSeries.safeParse(series("2024-01-01T00:00:00.123456Z"))
          .success,
      ).toBe(false);
    });
  },
);

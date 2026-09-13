import { describe, expect, it } from "vitest";

import { ACBus } from "../src/core";

describe("ACBus runtime validation", () => {
  it("accepts a valid bus", () => {
    const valid = {
      id: 1,
      number: 101,
      name: "BUS 101",
      available: true,
      bustype: "REF",
    };
    expect(() => ACBus.parse(valid)).not.toThrow();
    expect(ACBus.parse(valid).name).toBe("BUS 101");
  });

  it("throws on a wrong-typed required field", () => {
    const invalid = {
      id: "not-a-number",
      number: 101,
      name: "BUS 101",
      available: true,
    };
    expect(() => ACBus.parse(invalid)).toThrow();
  });

  it("throws when a required field is missing", () => {
    const invalid = {
      id: 1,
      number: 101,
      available: true,
    };
    expect(() => ACBus.parse(invalid)).toThrow();
  });

  it("throws on an out-of-enum value", () => {
    const invalid = {
      id: 1,
      number: 101,
      name: "BUS 101",
      available: true,
      bustype: "NOT_A_BUS_TYPE",
    };
    expect(() => ACBus.parse(invalid)).toThrow();
  });
});

import { describe, expect, it } from "vitest";
import { estimateSentence, formatBytes, sampleAge, unfilteredPartitions } from "./metered";

describe("formatBytes", () => {
  it("uses binary units, as BigQuery prices per TiB", () => {
    expect(formatBytes(1000)).toBe("1000 B");
    expect(formatBytes(10 * 2 ** 20)).toBe("10.0 MiB");
    expect(formatBytes(3 * 2 ** 40)).toBe("3.0 TiB");
  });
});

describe("estimateSentence", () => {
  const base = { metered: true, engine: "bigquery", exceeds_cap: false } as const;
  it("names size and price", () => {
    expect(estimateSentence({ ...base, bytes: 3 * 2 ** 40, est_cost_usd: 18.75 })).toBe(
      "This run scans ~3.0 TiB (~$18.75, on-demand estimate) on bigquery.",
    );
  });
  it("omits price where the engine bills time and warns past the cap", () => {
    expect(
      estimateSentence({
        ...base,
        engine: "snowflake",
        bytes: 2048,
        est_cost_usd: null,
        exceeds_cap: true,
        max_bytes_billed: 1024,
      }),
    ).toBe(
      "This run scans ~2.0 KiB on snowflake. That is above this connection's cap of 1.0 KiB, so snowflake will refuse it.",
    );
  });
});

describe("unfilteredPartitions", () => {
  it("flags a partition column no filter mentions", () => {
    expect(unfilteredPartitions(["timestamp"], [{ op: "select" }])).toEqual(["timestamp"]);
    expect(unfilteredPartitions(["timestamp"], [{ op: "filter", expr: "project = 'x'" }])).toEqual([
      "timestamp",
    ]);
  });
  it("accepts any filter that names it, quoted or not, any case", () => {
    expect(
      unfilteredPartitions(["timestamp"], [{ op: "filter", expr: `"TIMESTAMP" > '2026-01-01'` }]),
    ).toEqual([]);
    expect(unfilteredPartitions(["ts"], [{ op: "filter", expr: "ts_extra > 1" }])).toEqual(["ts"]);
  });
});

describe("sampleAge", () => {
  it("reads coarse", () => {
    const now = Date.parse("2026-11-02T12:00:00Z");
    expect(sampleAge("2026-11-02T11:59:30Z", now)).toBe("just now");
    expect(sampleAge("2026-11-02T11:15:00Z", now)).toBe("45m ago");
    expect(sampleAge("2026-11-02T09:00:00Z", now)).toBe("3h ago");
    expect(sampleAge("2026-10-30T12:00:00Z", now)).toBe("3d ago");
  });
});

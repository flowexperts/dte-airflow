import { describe, expect, it } from "vitest";
import {
  readsMetered,
  sampleAge,
  unfilteredPartitions,
} from "./metered";

describe("sampleAge", () => {
  it("reads coarse", () => {
    const now = Date.parse("2026-11-02T12:00:00Z");
    expect(sampleAge("2026-11-02T11:59:30Z", now)).toBe("just now");
    expect(sampleAge("2026-11-02T11:15:00Z", now)).toBe("45m ago");
    expect(sampleAge("2026-11-02T09:00:00Z", now)).toBe("3h ago");
    expect(sampleAge("2026-10-30T12:00:00Z", now)).toBe("3d ago");
  });
});

describe("readsMetered", () => {
  const sources = [
    { id: "sf", connection_id: "snow" },
    { id: "csv", connection_id: "local" },
  ];
  const connections = [
    { id: "snow", connection_type: "snowflake" },
    { id: "local", connection_type: "local_fs" },
  ];
  it("is true when any source sits on a warehouse connection", () => {
    expect(readsMetered([{ source_id: "csv" }, { source_id: "sf" }], sources, connections)).toBe(true);
    expect(readsMetered([{ source_id: "csv" }], sources, connections)).toBe(false);
  });
  it("is unknown until both lists load, so nothing billable fires early", () => {
    expect(readsMetered([{ source_id: "csv" }], undefined, connections)).toBeNull();
    expect(readsMetered([{ source_id: "csv" }], sources, undefined)).toBeNull();
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


import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/lib/api";
import { airflowRunHref, airflowTaskLogHref, eventLabel, timeline } from "./helpers";

describe("Airflow links", () => {
  it("builds the dag run and task log URLs from dag_id and run_id", () => {
    const run = "manual__2026-01-01T00:00:00+00:00";
    expect(airflowRunHref("dte__p1", run)).toBe(
      "dags/dte__p1/runs/manual__2026-01-01T00%3A00%3A00%2B00%3A00",
    );
    expect(airflowTaskLogHref("dte__p1", run)).toBe(
      "dags/dte__p1/runs/manual__2026-01-01T00%3A00%3A00%2B00%3A00/tasks/run",
    );
  });
});

const ev = (step_index: number | null, op: string, started_at: string): RunEvent => ({
  step_index,
  op,
  status: "completed",
  message: null,
  started_at,
  finished_at: started_at,
});

describe("timeline", () => {
  it("interleaves run phases and steps in the order they ran", () => {
    const events = [
      ev(0, "filter", "2026-01-01T00:00:02Z"),
      ev(null, "execute + write to json", "2026-01-01T00:00:03Z"),
      ev(null, "load source s1", "2026-01-01T00:00:01Z"),
    ];
    expect(timeline(events).map(eventLabel)).toEqual([
      "load source s1",
      "filter step 0",
      "execute + write to json",
    ]);
  });
});

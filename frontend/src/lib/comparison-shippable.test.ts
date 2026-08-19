import { describe, expect, it } from "vitest";
import { shippableCells } from "./comparison-shippable";
import type { ComparisonCell } from "./api";

function cell(over: Partial<ComparisonCell> = {}): ComparisonCell {
  return {
    cell_id: "c1",
    pipeline_id: "p1",
    run_id: "r1",
    status: "completed",
    cell: { provider: "regex" },
    documents: 5,
    null_rate: 0,
    error_count: 0,
    error_sample: null,
    cost_usd: 0,
    latency_p95_ms: 10,
    cache_hit_rate: 1,
    ...over,
  };
}

describe("shippableCells", () => {
  it("offers a completed cell that produced values", () => {
    const [only] = shippableCells([cell()]);
    expect(only!.shippable).toBe(true);
    expect(only!.reason).toBeNull();
  });

  it("refuses a failed run", () => {
    const [only] = shippableCells([cell({ status: "failed" })]);
    expect(only!.shippable).toBe(false);
    expect(only!.reason).toMatch(/did not finish/i);
  });

  it.each(["pending", "running"])("refuses a %s run", (status) => {
    const [only] = shippableCells([cell({ status })]);
    expect(only!.shippable).toBe(false);
    expect(only!.reason).toMatch(/still running/i);
  });

  /*
   * The case that motivates the whole filter. `on_error: null` fills nulls
   * rather than failing the run, so a cell where every call errored is
   * `completed` and green — and shipping it ships a pipeline that produces
   * empty columns on every document.
   */
  it("refuses a completed run where every row errored", () => {
    const [only] = shippableCells([
      cell({ status: "completed", documents: 5, error_count: 5 }),
    ]);
    expect(only!.shippable).toBe(false);
    expect(only!.reason).toMatch(/every row errored/i);
  });

  it("offers a run that errored on some rows but not all", () => {
    const [only] = shippableCells([cell({ documents: 5, error_count: 2 })]);
    expect(only!.shippable).toBe(true);
  });

  it("refuses a completed run that produced no documents at all", () => {
    const [only] = shippableCells([cell({ documents: 0, error_count: 0 })]);
    expect(only!.shippable).toBe(false);
    expect(only!.reason).toMatch(/no documents/i);
  });

  /*
   * Without labels the page computes no ranking; with them it computes ties
   * rather than winners. Either way the choice is the user's, so nothing
   * here may mark a preferred cell.
   */
  it("never marks a cell as recommended, even when one leads on score", () => {
    const out = shippableCells([
      cell({ cell_id: "a", macro_f1: 0.9, rank: 1 }),
      cell({ cell_id: "b", macro_f1: 0.4, rank: 2 }),
    ]);
    expect(out.every((c) => !("recommended" in c))).toBe(true);
  });

  it("preserves input order so the dropdown matches the cards", () => {
    const out = shippableCells([
      cell({ cell_id: "a" }),
      cell({ cell_id: "b", status: "failed" }),
      cell({ cell_id: "c" }),
    ]);
    expect(out.map((c) => c.cell.cell_id)).toEqual(["a", "b", "c"]);
  });
});

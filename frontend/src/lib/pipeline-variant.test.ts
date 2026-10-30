import { describe, expect, it } from "vitest";
import { isSweepVariant, rootPipelineId } from "./pipeline-variant";

/**
 * Mirrors `dte/evals/sweep.py:root_pipeline_id`. The two must agree: the
 * backend decides where a variant is stored, the frontend decides where
 * Compare sends you, and a disagreement puts the button on a pipeline the
 * sweep will not file its cells under.
 */

describe("rootPipelineId", () => {
  it("leaves a plain id alone", () => {
    expect(rootPipelineId("demo_eval_strict")).toBe("demo_eval_strict");
  });

  it("strips one variant suffix", () => {
    expect(rootPipelineId("demo_eval_strict__27fb9c1d2679")).toBe("demo_eval_strict");
  });

  it("strips a nested chain", () => {
    // The reported id.
    expect(rootPipelineId("demo_eval_strict__27fb9c1d2679__27fb9c1d2679__37f7b8bbec71")).toBe(
      "demo_eval_strict",
    );
  });

  it("keeps the eval twin suffix", () => {
    // The twin is what you compare *from*. Collapsing it would point
    // Compare at the transform pipeline, whose corpus check then refuses.
    expect(rootPipelineId("invoices__eval")).toBe("invoices__eval");
  });

  it("collapses a swept twin back to the twin", () => {
    expect(rootPipelineId("invoices__eval__27fb9c1d2679")).toBe("invoices__eval");
  });

  it.each([
    "orders__2024",
    "orders__abc",
    "orders__27fb9c1d267",
    "orders__27fb9c1d26799",
    "orders__27FB9C1D2679",
  ])("does not strip the lookalike %s", (id) => {
    // Someone's own naming convention must survive — stripping it would
    // send Compare to a pipeline that does not exist.
    expect(rootPipelineId(id)).toBe(id);
  });
});

describe("isSweepVariant", () => {
  it("is true for a sweep cell", () => {
    expect(isSweepVariant("demo_eval_strict__27fb9c1d2679")).toBe(true);
  });

  it("is false for the config someone authored", () => {
    expect(isSweepVariant("demo_eval_strict")).toBe(false);
  });

  it("is false for an eval twin", () => {
    expect(isSweepVariant("invoices__eval")).toBe(false);
  });
});

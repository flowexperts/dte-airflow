import { describe, expect, it } from "vitest";
import {
  PIPELINE_TYPE_TABS,
  parsePipelineType,
  pipelineListCopy,
  pipelineTypeLabel,
} from "./pipeline-type";

/**
 * `/pipelines?type=` drives both the filter and the sidebar's active state.
 *
 * The bug this replaces: only `transform` and `quality` were recognised, and
 * anything else fell through to `null`, which means "show everything". So
 * `?type=eval` rendered the full list under the heading "Pipelines" — the
 * filter appeared to work while filtering nothing, and eval pipelines had no
 * route of their own at all.
 */

describe("parsePipelineType", () => {
  it("recognises every type a pipeline can actually be", () => {
    expect(parsePipelineType("transform")).toBe("transform");
    expect(parsePipelineType("quality")).toBe("quality");
    expect(parsePipelineType("eval")).toBe("eval");
    expect(parsePipelineType("viz")).toBe("viz");
  });

  it("treats a missing type as the unfiltered list", () => {
    expect(parsePipelineType(undefined)).toBeNull();
  });

  it("treats an unknown type as unfiltered rather than guessing", () => {
    // Falling back to `transform` would hide pipelines under a heading that
    // claims to show them.
    expect(parsePipelineType("nonsense")).toBeNull();
  });
});

describe("PIPELINE_TYPE_TABS", () => {
  it("gives every pipeline type a nav entry", () => {
    // A type that can be created and then not found is worse than one that
    // cannot be created. Every value the builder offers needs a way back to
    // it.
    expect(PIPELINE_TYPE_TABS.map((t) => t.type)).toEqual([
      "transform",
      "quality",
      "eval",
      "viz",
    ]);
  });
});

describe("pipelineTypeLabel", () => {
  it("names an eval pipeline as one", () => {
    // The badge was a two-way branch (quality or else transform), so every
    // eval pipeline displayed "transform" — including on a list filtered to
    // eval, where the row contradicted the heading above it.
    expect(pipelineTypeLabel("eval")).toBe("eval");
    expect(pipelineTypeLabel("quality")).toBe("quality");
  });

  it("treats an absent type as transform", () => {
    expect(pipelineTypeLabel(null)).toBe("transform");
    expect(pipelineTypeLabel(undefined)).toBe("transform");
  });
});

describe("pipelineListCopy", () => {
  it("titles each filtered list distinctly", () => {
    expect(pipelineListCopy("eval").title).toBe("Eval pipelines");
    expect(pipelineListCopy("quality").title).toBe("Quality pipelines");
    expect(pipelineListCopy("transform").title).toBe("Transform pipelines");
    expect(pipelineListCopy(null).title).toBe("Pipelines");
  });

  it("explains what an eval pipeline is for, since it has no output", () => {
    expect(pipelineListCopy("eval").lede).toMatch(/scor/i);
  });
});

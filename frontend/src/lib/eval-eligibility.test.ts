import { describe, expect, it } from "vitest";
import { eligibleEvalPipelines } from "./eval-eligibility";
import type { Pipeline } from "./api";

/**
 * Which pipelines may be scored against a given eval set.
 *
 * The bug this replaces: the picker filtered on `pipeline_type === "eval"`
 * alone, so it offered pipelines reading a *different* documents source.
 * Labels join by document hash, so scoring one of those matches nothing and
 * reports zero — a green run that measured no documents, presenting as a
 * broken extractor.
 */

const p = (id: string, sources: string[], type = "eval") =>
  ({
    id,
    name: id,
    sources: sources.map((source_id) => ({ source_id })),
    steps: [],
    pipeline_type: type,
  }) as unknown as Pipeline;

describe("eligibleEvalPipelines", () => {
  it("keeps eval pipelines reading the set's corpus", () => {
    const rows = eligibleEvalPipelines([p("a", ["docs_a"])], "docs_a");
    expect(rows.map((r) => r.id)).toEqual(["a"]);
  });

  it("drops eval pipelines reading a different corpus", () => {
    expect(eligibleEvalPipelines([p("b", ["docs_b"])], "docs_a")).toEqual([]);
  });

  it("drops pipelines that are not eval pipelines", () => {
    expect(eligibleEvalPipelines([p("t", ["docs_a"], "transform")], "docs_a")).toEqual([]);
  });

  it("keeps a pipeline carrying the corpus alongside other sources", () => {
    // Presence, not exclusivity: a pipeline joining something else next to
    // the documents is still scoring the right documents.
    const rows = eligibleEvalPipelines([p("m", ["other", "docs_a"])], "docs_a");
    expect(rows.map((r) => r.id)).toEqual(["m"]);
  });

  it("returns nothing when the set's source is unknown", () => {
    // Better to offer nothing than to offer everything: the picker's job is
    // to make the invalid combination unreachable, and an empty list is a
    // question the user can answer.
    expect(eligibleEvalPipelines([p("a", ["docs_a"])], undefined)).toEqual([]);
  });

  it("tolerates a pipeline with no sources", () => {
    expect(eligibleEvalPipelines([p("n", [])], "docs_a")).toEqual([]);
  });
});

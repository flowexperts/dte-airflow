import { describe, expect, it } from "vitest";
import {
  buildMatrix,
  cellCount,
  draftFromMatrix,
  regexAvailability,
  unknownAxes,
  type CompareDraft,
} from "./compare-matrix";

/**
 * The matrix a Compare run expands to.
 *
 * The old sweep launcher took a free-text axis and a comma-separated value
 * list, with help text that contradicted its own docstring — the docstring
 * promised "providers × models × prompts", the form offered one axis. Worse,
 * it offered `regex` as a provider value against a structure step with no
 * per-field `pattern`, which is guaranteed to score zero. The literal
 * three-way comparison the product exists for was a trap.
 */

const draft = (over: Partial<CompareDraft> = {}): CompareDraft => ({
  providers: [],
  models: [],
  instructions: [],
  ...over,
});

describe("buildMatrix", () => {
  it("builds a provider axis", () => {
    expect(buildMatrix(draft({ providers: ["claude", "openai"] }))).toEqual({
      provider: ["claude", "openai"],
    });
  });

  it("puts models on params.model, where the step actually keeps them", () => {
    // Not `model` — that key holds the field spec. Getting this wrong
    // replaces the whole data model with a string.
    expect(buildMatrix(draft({ models: ["claude-opus-5"] }))).toEqual({
      "params.model": ["claude-opus-5"],
    });
  });

  it("puts instructions on model.instructions", () => {
    expect(buildMatrix(draft({ instructions: ["terse", "verbose"] }))).toEqual({
      "model.instructions": ["terse", "verbose"],
    });
  });

  it("combines axes into one cartesian request", () => {
    // The shape the API has always accepted and the form never offered.
    expect(buildMatrix(draft({ providers: ["claude", "openai"], models: ["a", "b"] }))).toEqual({
      provider: ["claude", "openai"],
      "params.model": ["a", "b"],
    });
  });

  it("omits an axis with nothing selected", () => {
    // An empty list is rejected by _expand_matrix with a 422. Sending one
    // would turn "I only want to vary the provider" into an error.
    expect(buildMatrix(draft({ providers: ["claude"], models: [] }))).toEqual({
      provider: ["claude"],
    });
  });

  it("returns an empty matrix when nothing is selected", () => {
    expect(buildMatrix(draft())).toEqual({});
  });

  it("drops blank instruction variants", () => {
    // Three textareas, two filled. The empty one is not a config.
    expect(buildMatrix(draft({ instructions: ["terse", "   ", ""] }))).toEqual({
      "model.instructions": ["terse"],
    });
  });

  it("trims instruction whitespace", () => {
    expect(buildMatrix(draft({ instructions: ["  be terse  "] }))).toEqual({
      "model.instructions": ["be terse"],
    });
  });

  it("de-duplicates a repeated value", () => {
    // Two identical cells cost twice and rank against each other, which
    // reads as "the same config scored differently" — the exact thing that
    // makes people stop trusting a comparison.
    expect(buildMatrix(draft({ providers: ["claude", "claude"] }))).toEqual({
      provider: ["claude"],
    });
  });
});

describe("cellCount", () => {
  it("is zero when nothing is selected", () => {
    expect(cellCount(draft())).toBe(0);
  });

  it("counts a single axis", () => {
    expect(cellCount(draft({ providers: ["claude", "openai", "regex"] }))).toBe(3);
  });

  it("multiplies across axes", () => {
    // This is the number the user is about to spend against, so it must
    // match what the backend expands to exactly.
    expect(cellCount(draft({ providers: ["claude", "openai"], models: ["a", "b", "c"] }))).toBe(6);
  });

  it("ignores blank instruction slots", () => {
    expect(cellCount(draft({ providers: ["claude"], instructions: ["a", "", "  "] }))).toBe(1);
  });
});

describe("regexAvailability", () => {
  const withPatterns = [
    { name: "total", pattern: "Total:\\s*([\\d.]+)" },
    { name: "vendor", pattern: "From:\\s*(.+)" },
  ];

  it("is available when every field has a pattern", () => {
    expect(regexAvailability(withPatterns)).toEqual({ available: true });
  });

  it("is unavailable when a field has no pattern", () => {
    // The trap this closes: sweeping provider=regex against a step with no
    // patterns runs, produces nulls, and scores ~0 — which reads as "regex
    // is bad at this" rather than "regex was never configured".
    const result = regexAvailability([
      { name: "total", pattern: "Total:\\s*([\\d.]+)" },
      { name: "vendor", pattern: null },
    ]);
    expect(result.available).toBe(false);
  });

  it("names the fields that are missing one", () => {
    // "Add patterns" is not actionable. "vendor and due_date have none" is.
    const result = regexAvailability([
      { name: "total", pattern: "x" },
      { name: "vendor", pattern: null },
      { name: "due_date", pattern: "" },
    ]);
    expect(result.available).toBe(false);
    if (!result.available) {
      expect(result.missing).toEqual(["vendor", "due_date"]);
    }
  });

  it("treats a whitespace-only pattern as missing", () => {
    const result = regexAvailability([{ name: "total", pattern: "   " }]);
    expect(result.available).toBe(false);
  });

  it("is unavailable with no fields at all", () => {
    expect(regexAvailability([]).available).toBe(false);
  });
});

describe("draftFromMatrix", () => {
  /*
   * The inverse of buildMatrix, and the reason the matrix can be *stored*
   * at all. Reopening a saved comparison has to restore the chips that
   * produced it — without this the panel renders empty and the next save
   * silently discards every axis the user configured.
   */
  it("round-trips a full matrix", () => {
    const matrix = {
      provider: ["claude", "regex"],
      "params.model": ["claude-opus-5"],
      "model.instructions": ["be terse"],
    };
    expect(buildMatrix(draftFromMatrix(matrix))).toEqual(matrix);
  });

  it("round-trips a provider-only matrix", () => {
    const matrix = { provider: ["claude", "openai"] };
    expect(buildMatrix(draftFromMatrix(matrix))).toEqual(matrix);
  });

  it("reads null and undefined as an empty draft", () => {
    for (const empty of [null, undefined]) {
      const draft = draftFromMatrix(empty);
      expect(draft).toEqual({ providers: [], models: [], instructions: [] });
      expect(buildMatrix(draft)).toEqual({});
    }
  });

  it("ignores axes it does not own rather than dropping them silently", () => {
    /*
     * `params.max_tokens` is a legal sweep axis the panel has no control
     * for. Parsing it into the draft would be a lie; the panel reports it
     * instead, because a saved axis that vanishes on the next save is the
     * worst outcome.
     */
    const draft = draftFromMatrix({ "params.max_tokens": [1000, 2000] });
    expect(draft.providers).toEqual([]);
    expect(unknownAxes({ "params.max_tokens": [1000] })).toEqual(["params.max_tokens"]);
  });

  it("coerces non-string values to strings", () => {
    // JSONB round-trips numbers as numbers; the chips are strings.
    expect(draftFromMatrix({ "params.model": [5] }).models).toEqual(["5"]);
  });
});

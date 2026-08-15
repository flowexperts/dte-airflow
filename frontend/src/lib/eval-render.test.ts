import { describe, expect, it } from "vitest";
import { intervalsOverlap } from "./api";
import { pct, scoreTone } from "@/components/evals/score";

/**
 * The rendering rules that keep the leaderboard honest. Each of these has a
 * specific lie it prevents, and each lie is one the UI would tell silently.
 */

describe("pct", () => {
  it("renders a null score as an em dash, never as 0%", () => {
    // An unmeasured holdout and a holdout that scored zero must not look the
    // same — one is missing data, the other is a result.
    expect(pct(null)).toBe("—");
    expect(pct(undefined)).toBe("—");
    expect(pct(0)).toBe("0.0%");
  });

  it("formats to one decimal", () => {
    expect(pct(0.9412)).toBe("94.1%");
    expect(pct(1)).toBe("100.0%");
  });
});

describe("scoreTone", () => {
  it("gives null its own neutral tone rather than the failing colour", () => {
    expect(scoreTone(null)).toBe("var(--subtle)");
    expect(scoreTone(0)).toBe("var(--red)");
  });

  it("bands high / middling / low", () => {
    expect(scoreTone(0.95)).toBe("var(--green)");
    expect(scoreTone(0.75)).toBe("var(--gold)");
    expect(scoreTone(0.4)).toBe("var(--red)");
  });
});

describe("intervalsOverlap", () => {
  it("treats overlapping confidence intervals as indistinguishable", () => {
    // 94.1% vs 91.7% on a small n. Ranking these 1 and 2 renders sampling
    // noise as a decision, and people act on it.
    expect(intervalsOverlap([0.7, 0.99], [0.65, 0.98])).toBe(true);
  });

  it("separates intervals that do not touch", () => {
    expect(intervalsOverlap([0.9, 0.99], [0.1, 0.4])).toBe(false);
  });

  it("counts a shared endpoint as overlapping", () => {
    expect(intervalsOverlap([0.5, 0.7], [0.7, 0.9])).toBe(true);
  });

  it("refuses to claim separation when an interval is missing", () => {
    // No interval means we do not know the spread. Defaulting to "distinct"
    // would rank on a point estimate alone, which is the exact failure the
    // interval exists to prevent.
    expect(intervalsOverlap(undefined, [0.1, 0.4])).toBe(false);
    expect(intervalsOverlap([0.1, 0.4], undefined)).toBe(false);
  });
});

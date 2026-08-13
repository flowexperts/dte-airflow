import { describe, expect, it } from "vitest";
import { resolveHighlight, type Word } from "./provenance";

/** A line of words laid out left-to-right at a given vertical band. */
function line(top: number, ...texts: string[]): Word[] {
  let x = 50;
  return texts.map((text) => {
    const w = { text, x0: x, x1: x + text.length * 6, top, bottom: top + 10 };
    x = w.x1 + 4;
    return w;
  });
}

const PAGE = { width: 612, height: 792 };

const WORDS: Word[] = [
  ...line(100, "ACME", "Freight", "Ltd."),
  ...line(140, "Invoice", "INV-1001"),
  ...line(180, "Total:", "$1,240.50"),
];

const block = (words: Word[] = WORDS) => ({ words, ...PAGE });

describe("resolveHighlight", () => {
  it("boxes a single word", () => {
    const rects = resolveHighlight(block(), { quote: "$1,240.50" });
    expect(rects).toHaveLength(1);
    // Normalised to fractions of the page, so the renderer can scale to any
    // canvas size without the geometry knowing about pixels.
    const r = rects[0]!;
    expect(r.x).toBeGreaterThan(0);
    expect(r.x).toBeLessThan(1);
    expect(r.y).toBeCloseTo(180 / 792, 5);
    expect(r.h).toBeCloseTo(10 / 792, 5);
  });

  it("merges words of a quote that sits on one line", () => {
    const rects = resolveHighlight(block(), { quote: "ACME Freight" });
    expect(rects).toHaveLength(1);
    const r = rects[0]!;
    expect(r.x).toBeCloseTo(50 / 612, 5);
    // Spans through "Freight" but stops before "Ltd."
    expect(r.x + r.w).toBeLessThan((50 + 4 * 6 + 4 + 7 * 6 + 4) / 612 + 0.01);
  });

  it("splits a quote spanning two lines into one rect per line", () => {
    // The whole point: a single bounding box around a two-line quote covers
    // the entire width of the page including unrelated text between the
    // lines' ends and starts.
    const rects = resolveHighlight(block(), { quote: "Ltd. Invoice" });
    expect(rects).toHaveLength(2);
    expect(rects[0]!.y).toBeLessThan(rects[1]!.y);
  });

  it("is insensitive to case and to whitespace runs", () => {
    expect(resolveHighlight(block(), { quote: "acme   FREIGHT" })).toHaveLength(1);
    expect(resolveHighlight(block(), { quote: "\n Total: \t" })).toHaveLength(1);
  });

  it("returns nothing when the quote is not on the page", () => {
    // A wrong highlight is worse than none: the UI shows the quote as text
    // rather than boxing an approximation.
    expect(resolveHighlight(block(), { quote: "Northwind" })).toEqual([]);
  });

  it("returns nothing when the provider supplied no word boxes", () => {
    // pypdf extracts text without layout. Degrade, don't guess.
    expect(resolveHighlight(block([]), { quote: "ACME" })).toEqual([]);
  });

  it("returns nothing when there is no quote to match", () => {
    expect(resolveHighlight(block(), {})).toEqual([]);
    expect(resolveHighlight(block(), { quote: "" })).toEqual([]);
    expect(resolveHighlight(block(), { quote: "   " })).toEqual([]);
  });

  it("picks the first occurrence when a quote repeats", () => {
    const words = [...line(100, "total"), ...line(200, "total")];
    const rects = resolveHighlight({ words, ...PAGE }, { quote: "total" });
    expect(rects).toHaveLength(1);
    expect(rects[0]!.y).toBeCloseTo(100 / 792, 5);
  });

  it("does not match a quote that merely spans a word boundary", () => {
    // "GHTLTD" concatenates the tail of one word and the head of the next.
    // Matching it would box two words that never contained the quote.
    expect(resolveHighlight(block(), { quote: "ght Ltd" })).toEqual([]);
  });

  it("degrades when the page has no dimensions", () => {
    // Without a page size there is no scale factor and any rect would be a
    // guess in the wrong coordinate space.
    const rects = resolveHighlight(
      { words: WORDS, width: null, height: null },
      { quote: "ACME" },
    );
    expect(rects).toEqual([]);
  });
});

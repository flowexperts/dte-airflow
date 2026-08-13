/** Mapping a structured field back to the region of the page it came from.
 *
 *  Pure geometry, deliberately separate from any renderer: the same rects
 *  work over a pdf.js canvas, a raster, or a plain text facsimile.
 *
 *  **Why quotes and not character offsets.** Provenance carries
 *  `char_start`/`char_end`, but those index into `page.extract_text()` while
 *  the boxes come from `page.extract_words()` — two independent pdfplumber
 *  passes with no guaranteed offset alignment. Trusting the offsets produces
 *  highlights that are subtly off, and subtly-off is the worst outcome here:
 *  it looks authoritative while pointing at the wrong number. So the quote is
 *  matched against the word sequence instead, and anything that does not
 *  match exactly yields no box at all.
 */

export interface Word {
  text: string;
  x0: number;
  x1: number;
  top: number;
  bottom: number;
}

export interface PageBlock {
  words: Word[];
  width: number | null;
  height: number | null;
}

export interface Provenance {
  quote?: string | null;
  page?: number | null;
  confidence?: number | null;
  char_start?: number | null;
  char_end?: number | null;
}

/** A highlight, in fractions of the page (0–1), origin top-left. */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Strip everything that varies between a model's quote and the page's own
 *  tokenisation, keeping only letters and digits.
 *
 *  Whitespace is the obvious case — pdfplumber splits on it, so a quote's
 *  internal spacing carries no information. Punctuation matters just as much
 *  in practice: the page reads `$1,240.50` and a model will happily quote
 *  `1240.50`. Both name the same number in the same place, and refusing to
 *  highlight over a currency symbol would make the feature look broken on the
 *  commonest field of the commonest document.
 *
 *  This only affects *locating* a value, never verifying it — the value shown
 *  beside the box is the extracted one, untouched. And because matches are
 *  still anchored to word boundaries, dropping punctuation cannot let a match
 *  start midway through a token. */
const squash = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");

export function resolveHighlight(block: PageBlock, prov: Provenance): Rect[] {
  const { width, height } = block;
  if (!width || !height) return [];

  const target = squash(prov.quote ?? "");
  if (!target) return [];

  const words = block.words ?? [];
  if (words.length === 0) return [];

  // Concatenate the page's words and remember where each one begins, so a
  // match can be required to land on word boundaries.
  const starts: number[] = [];
  const ends: number[] = [];
  let joined = "";
  for (const w of words) {
    starts.push(joined.length);
    joined += squash(w.text);
    ends.push(joined.length);
  }

  // First occurrence, scanning forward: a repeated quote must resolve to the
  // same box on every render, and "the first one" is the only choice that is
  // stable without more information than provenance gives us.
  let at = joined.indexOf(target);
  while (at !== -1) {
    const first = starts.indexOf(at);
    const last = ends.indexOf(at + target.length);
    // Both ends must coincide with word boundaries. Without this a quote can
    // match across a boundary — the tail of one word plus the head of the
    // next — and box two words that never contained it.
    if (first !== -1 && last !== -1 && last >= first) {
      return groupIntoLines(words.slice(first, last + 1)).map((run) =>
        bounds(run, width, height),
      );
    }
    at = joined.indexOf(target, at + 1);
  }

  return [];
}

/** Split a run of words into visual lines.
 *
 *  A quote that wraps must produce one rect per line. A single bounding box
 *  around the whole run would span from the start of the first line to the
 *  end of the last, swallowing every unrelated word in between — on a
 *  two-column invoice that is most of the page.
 */
function groupIntoLines(run: Word[]): Word[][] {
  const lines: Word[][] = [];
  for (const w of run) {
    const current = lines[lines.length - 1];
    // Compare against the line's own height rather than a fixed threshold, so
    // this holds for both 8pt footnotes and 24pt headings.
    const prev = current?.[current.length - 1];
    const tolerance = prev ? (prev.bottom - prev.top) / 2 : 0;
    if (prev && Math.abs(w.top - prev.top) <= tolerance) {
      current.push(w);
    } else {
      lines.push([w]);
    }
  }
  return lines;
}

function bounds(run: Word[], width: number, height: number): Rect {
  const x0 = Math.min(...run.map((w) => w.x0));
  const x1 = Math.max(...run.map((w) => w.x1));
  const top = Math.min(...run.map((w) => w.top));
  const bottom = Math.max(...run.map((w) => w.bottom));
  return {
    x: x0 / width,
    y: top / height,
    w: (x1 - x0) / width,
    h: (bottom - top) / height,
  };
}

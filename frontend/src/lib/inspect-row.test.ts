import { describe, expect, it } from "vitest";
import { inspectableRow } from "./inspect-row";

const KEY = "a".repeat(64);
const EXTRACT = "b".repeat(64);

const row = (over: Record<string, unknown> = {}) => ({
  path: "/docs/inv-1001.pdf",
  filename: "inv-1001.pdf",
  page: 2,
  artifact_ref: `artifact://${KEY}`,
  extract_meta: { key: EXTRACT, provider: "pdfplumber", cached: true },
  invoice_no: "INV-1001",
  total: 1240.5,
  structure_meta: JSON.stringify({
    provider: "claude",
    fields: {
      invoice_no: { quote: "INV-1001", page: 2, confidence: 0.99 },
      total: { quote: "$1,240.50", page: 2, confidence: 0.97 },
    },
  }),
  ...over,
});

describe("inspectableRow", () => {
  it("pulls the document key out of the artifact ref", () => {
    expect(inspectableRow(row())?.docKey).toBe(KEY);
  });

  it("carries the extract key so word boxes can be fetched", () => {
    expect(inspectableRow(row())?.extractKey).toBe(EXTRACT);
  });

  it("pairs each declared field with its value and provenance", () => {
    const fields = inspectableRow(row())!.fields;
    expect(fields.map((f) => f.name).sort()).toEqual(["invoice_no", "total"]);
    const total = fields.find((f) => f.name === "total")!;
    expect(total.value).toBe(1240.5);
    expect(total.provenance?.quote).toBe("$1,240.50");
  });

  it("parses structure_meta whether it arrives as a string or an object", () => {
    // DuckDB hands back JSON columns as strings; the preview endpoint may
    // have already parsed them. Both shapes reach this code.
    const parsed = row({ structure_meta: JSON.parse(row().structure_meta) });
    expect(inspectableRow(parsed)?.fields).toHaveLength(2);
  });

  it("survives structure_meta that is not valid JSON", () => {
    // Never throw inside a table cell renderer: one malformed row would
    // blank the whole preview.
    const r = inspectableRow(row({ structure_meta: "{not json" }));
    expect(r?.docKey).toBe(KEY);
    expect(r?.fields).toEqual([]);
  });

  it("works for an extract-only row with no structure step", () => {
    const r = inspectableRow(row({ structure_meta: undefined }));
    expect(r?.docKey).toBe(KEY);
    expect(r?.fields).toEqual([]);
  });

  it("keeps a declared field whose value came back null", () => {
    // A miss is the most important row to inspect — the user is asking why
    // nothing was found. Dropping it hides exactly that case.
    const r = inspectableRow(row({ total: null }));
    const total = r!.fields.find((f) => f.name === "total");
    expect(total).toBeDefined();
    expect(total!.value).toBeNull();
  });

  it("takes the page from the row when provenance has none", () => {
    const r = inspectableRow(row({ structure_meta: JSON.stringify({ fields: { total: null } }) }));
    expect(r?.page).toBe(2);
  });

  it("is null for a row with no document behind it", () => {
    expect(inspectableRow({ id: 1, name: "not a document" })).toBeNull();
    expect(inspectableRow(row({ artifact_ref: null }))).toBeNull();
  });

  it("rejects a malformed artifact ref rather than building a broken link", () => {
    expect(inspectableRow(row({ artifact_ref: "artifact://nope" }))).toBeNull();
    expect(inspectableRow(row({ artifact_ref: `/etc/passwd` }))).toBeNull();
  });
});

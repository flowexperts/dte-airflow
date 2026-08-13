import { describe, expect, it } from "vitest";
import { SYSTEM_COLUMNS, visibleColumns } from "./system-columns";

describe("visibleColumns", () => {
  it("hides the plumbing an extracted row carries", () => {
    expect(
      visibleColumns([
        "invoice_no",
        "total",
        "artifact_ref",
        "extract_meta",
        "structure_meta",
        "block_index",
      ]),
    ).toEqual(["invoice_no", "total"]);
  });

  it("preserves the order of what is left", () => {
    expect(visibleColumns(["b", "artifact_ref", "a", "extract_meta", "c"])).toEqual([
      "b",
      "a",
      "c",
    ]);
  });

  it("leaves an ordinary pipeline untouched", () => {
    const cols = ["id", "name", "amount"];
    expect(visibleColumns(cols)).toEqual(cols);
  });

  it("keeps page and filename, which are the user's own data", () => {
    // `page` reads like plumbing but is genuinely useful — it tells you which
    // page of a 500-page contract a row came from. It is not on the list.
    expect(visibleColumns(["page", "filename"])).toEqual(["page", "filename"]);
    expect(SYSTEM_COLUMNS.has("page")).toBe(false);
  });

  it("does not mutate its input", () => {
    const cols = ["a", "artifact_ref"];
    visibleColumns(cols);
    expect(cols).toEqual(["a", "artifact_ref"]);
  });
});

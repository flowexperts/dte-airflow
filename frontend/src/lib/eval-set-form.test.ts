import { describe, expect, it } from "vitest";
import {
  FIELD_TYPES,
  toEvalSetPayload,
  validateEvalSetForm,
  type EvalSetDraft,
} from "./eval-set-form";

/**
 * Creating an eval set is where a corpus gets its contract. Most of what can
 * go wrong here is silent later — a misspelled field name scores zero
 * forever, and zero looks exactly like a bad extractor.
 */

const valid: EvalSetDraft = {
  id: "invoices",
  name: "Invoices",
  source_id: "docs_src",
  fields: [{ name: "total", type: "numeric", description: "the total" }],
};

describe("validateEvalSetForm", () => {
  it("accepts a complete draft", () => {
    expect(validateEvalSetForm(valid)).toEqual({});
  });

  it("requires a name", () => {
    expect(validateEvalSetForm({ ...valid, name: "  " })).toHaveProperty("name");
  });

  it("requires a source", () => {
    expect(validateEvalSetForm({ ...valid, source_id: "" })).toHaveProperty("source_id");
  });

  it("requires at least one field", () => {
    // A set with no fields scores nothing. The backend rejects it too, but
    // finding out after a round trip is a worse way to learn it.
    expect(validateEvalSetForm({ ...valid, fields: [] })).toHaveProperty("fields");
  });

  it("rejects a blank field name", () => {
    expect(
      validateEvalSetForm({ ...valid, fields: [{ name: "  ", type: "numeric" }] }),
    ).toHaveProperty("fields");
  });

  it("rejects duplicate field names", () => {
    // Two specs with one name means one of them is silently unscored.
    const errs = validateEvalSetForm({
      ...valid,
      fields: [
        { name: "total", type: "numeric" },
        { name: "total", type: "string" },
      ],
    });
    expect(errs.fields).toMatch(/total/);
  });

  it("allows an empty id — the server generates one", () => {
    expect(validateEvalSetForm({ ...valid, id: "" })).toEqual({});
  });

  it("rejects an id with characters that would need escaping in a URL", () => {
    // The id lands in /eval-sets/{id} and in every API path built from it.
    expect(validateEvalSetForm({ ...valid, id: "my set!" })).toHaveProperty("id");
  });
});

describe("FIELD_TYPES", () => {
  it("offers only comparators the backend knows", () => {
    // An unknown type is rejected at save; offering one in a dropdown would
    // make the UI the source of the error.
    expect(FIELD_TYPES).toContain("numeric");
    expect(FIELD_TYPES).toContain("string");
    expect(FIELD_TYPES).toContain("date");
    expect(FIELD_TYPES).not.toContain("nonsense");
  });

  it("does not offer llm_judge as an ordinary choice", () => {
    // It costs money, is non-deterministic, and flatters an extractor it
    // shares a family with. It must be chosen deliberately, not landed on
    // while scrolling a list of types.
    expect(FIELD_TYPES).not.toContain("llm_judge");
  });
});

describe("toEvalSetPayload", () => {
  it("trims names and drops empty descriptions", () => {
    const body = toEvalSetPayload({
      ...valid,
      name: "  Invoices  ",
      fields: [{ name: " total ", type: "numeric", description: "   " }],
    });
    expect(body.name).toBe("Invoices");
    expect(body.field_specs[0]!.name).toBe("total");
    expect(body.field_specs[0]).not.toHaveProperty("description");
  });

  it("omits a blank id so the server generates one", () => {
    expect(toEvalSetPayload({ ...valid, id: "" })).not.toHaveProperty("id");
    expect(toEvalSetPayload(valid).id).toBe("invoices");
  });

  it("carries a numeric tolerance through as comparator options", () => {
    // The default is exact. A corpus of money needs a tolerance, and this is
    // the only place to say so before the first run.
    const body = toEvalSetPayload({
      ...valid,
      fields: [{ name: "total", type: "numeric", rel_tol: "0.001" }],
    });
    expect(body.field_specs[0]!.comparator).toEqual({ rel_tol: 0.001 });
  });

  it("leaves comparator absent when no tolerance is given", () => {
    expect(toEvalSetPayload(valid).field_specs[0]).not.toHaveProperty("comparator");
  });

  it("ignores a tolerance typed on a non-numeric field", () => {
    // A rel_tol on a string field would be silently meaningless; sending it
    // implies the scorer honours it.
    const body = toEvalSetPayload({
      ...valid,
      fields: [{ name: "vendor", type: "string", rel_tol: "0.5" }],
    });
    expect(body.field_specs[0]).not.toHaveProperty("comparator");
  });
});

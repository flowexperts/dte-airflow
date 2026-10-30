import { describe, expect, it } from "vitest";
import { fromFields, toFields } from "./params";

describe("notifier params ⇄ form fields", () => {
  it("drops blanks and keeps text as text", () => {
    expect(fromFields({ to: "a@x.com, b@x.com", subject: "", smtp_conn_id: " team_email " }))
      .toEqual({ to: "a@x.com, b@x.com", smtp_conn_id: "team_email" });
  });

  it("parses JSON lists and objects, for list-typed args", () => {
    expect(fromFields({ cc: '["a@x.com"]', custom_headers: '{"X-A": "1"}' }))
      .toEqual({ cc: ["a@x.com"], custom_headers: { "X-A": "1" } });
  });

  it("keeps a bracketed value that isn't JSON as text", () => {
    expect(fromFields({ text: "[DTE] {{ dte_message }}" })).toEqual({ text: "[DTE] {{ dte_message }}" });
  });

  it("round-trips saved params", () => {
    const saved = { to: "a@x.com", cc: ["b@x.com"], subject: "s" };
    expect(fromFields(toFields(saved))).toEqual(saved);
  });
});

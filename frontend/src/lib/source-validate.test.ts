import { describe, expect, it } from "vitest";
import { validateSource } from "./source-validate";

describe("validateSource", () => {
  it("lets a new source go without an id: the server generates it", () => {
    expect(validateSource({ id: "" }, "create")).toBeNull();
  });
  it("still checks the id of an existing source", () => {
    expect(validateSource({ id: "" }, "edit")).toMatch(/required/);
    expect(validateSource({ id: "a b" }, "edit")).toMatch(/only contain/);
    expect(validateSource({ id: "orders_1" }, "edit")).toBeNull();
  });
});

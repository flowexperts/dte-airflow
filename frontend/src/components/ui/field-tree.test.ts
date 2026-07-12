import { describe, expect, it } from "vitest";
import {
  buildTree,
  findNode,
  toDisplay,
  toPath,
  toWire,
} from "./field-tree";

describe("toDisplay / toWire / toPath", () => {
  it("converts wire to display and back", () => {
    expect(toDisplay("order__amount")).toBe("order.amount");
    expect(toWire("order.amount")).toBe("order__amount");
  });

  it("is idempotent on already-wire input", () => {
    expect(toWire("order__amount")).toBe("order__amount");
  });

  it("preserves reserved _dlt_* names", () => {
    expect(toDisplay("_dlt_id")).toBe("_dlt_id");
    expect(toDisplay("_dlt_load_id")).toBe("_dlt_load_id");
    expect(toWire("_dlt_id")).toBe("_dlt_id");
    expect(toPath("_dlt_load_id")).toEqual(["_dlt_load_id"]);
  });

  it("splits a wire name into path segments", () => {
    expect(toPath("order__amount")).toEqual(["order", "amount"]);
    expect(toPath("user__address__city")).toEqual(["user", "address", "city"]);
    expect(toPath("id")).toEqual(["id"]);
  });
});

describe("buildTree", () => {
  it("returns [] for empty input", () => {
    expect(buildTree([])).toEqual([]);
  });

  it("keeps flat fields as top-level leaves", () => {
    const tree = buildTree([
      { name: "id", type: "string" },
      { name: "amount", type: "float64" },
    ]);
    expect(tree).toHaveLength(2);
    expect(tree[0]).toMatchObject({ name: "id", wire: "id", type: "string" });
    expect(tree[0].children).toBeUndefined();
  });

  it("groups one level of nesting", () => {
    const tree = buildTree([
      { name: "order__amount", type: "float64" },
      { name: "order__currency", type: "string" },
    ]);
    expect(tree).toHaveLength(1);
    const order = tree[0];
    expect(order.name).toBe("order");
    expect(order.children).toHaveLength(2);
    expect(order.children![0]).toMatchObject({
      name: "amount",
      wire: "order__amount",
      path: ["order", "amount"],
      type: "float64",
    });
  });

  it("supports deep nesting", () => {
    const tree = buildTree([
      { name: "user__address__city", type: "string" },
    ]);
    expect(tree[0].name).toBe("user");
    const addr = tree[0].children![0];
    expect(addr.name).toBe("address");
    const city = addr.children![0];
    expect(city).toMatchObject({
      name: "city",
      wire: "user__address__city",
      path: ["user", "address", "city"],
      type: "string",
    });
  });

  it("keeps _dlt_* as flat leaves", () => {
    const tree = buildTree([
      { name: "_dlt_id", type: "string" },
      { name: "_dlt_load_id", type: "string" },
    ]);
    expect(tree).toHaveLength(2);
    expect(tree[0].children).toBeUndefined();
    expect(tree[0].wire).toBe("_dlt_id");
  });
});

describe("findNode", () => {
  const tree = buildTree([
    { name: "id", type: "string" },
    { name: "user__address__city", type: "string" },
  ]);

  it("finds a top-level leaf", () => {
    expect(findNode(tree, "id")?.wire).toBe("id");
  });

  it("finds a nested leaf", () => {
    expect(findNode(tree, "user__address__city")?.name).toBe("city");
  });

  it("returns null for unknown wire", () => {
    expect(findNode(tree, "nope")).toBeNull();
  });
});

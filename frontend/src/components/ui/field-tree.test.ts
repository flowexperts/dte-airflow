import { describe, expect, it } from "vitest";
import {
  buildTree,
  findNode,
  toDisplay,
  toPath,
  toWire,
} from "./field-tree";

describe("toDisplay / toWire / toPath", () => {
  it("dot form is identity for display", () => {
    expect(toDisplay("order.amount")).toBe("order.amount");
  });

  it("normalises legacy `__`-flat input to dot form", () => {
    expect(toWire("order__amount")).toBe("order.amount");
    expect(toWire("user__address__city")).toBe("user.address.city");
  });

  it("is idempotent on dot-form input", () => {
    expect(toWire("order.amount")).toBe("order.amount");
  });

  it("preserves reserved _dlt_* names", () => {
    expect(toDisplay("_dlt_id")).toBe("_dlt_id");
    expect(toWire("_dlt_id")).toBe("_dlt_id");
    expect(toWire("_dlt_load_id")).toBe("_dlt_load_id");
    expect(toPath("_dlt_load_id")).toEqual(["_dlt_load_id"]);
  });

  it("splits dot-form into path segments", () => {
    expect(toPath("order.amount")).toEqual(["order", "amount"]);
    expect(toPath("user.address.city")).toEqual(["user", "address", "city"]);
    expect(toPath("id")).toEqual(["id"]);
  });
});

describe("buildTree from backend children[]", () => {
  it("walks a nested SchemaField tree", () => {
    const tree = buildTree([
      { name: "id", type: "string" },
      {
        name: "order",
        type: "struct",
        children: [
          { name: "amount", type: "float64" },
          { name: "currency", type: "string" },
        ],
      },
      {
        name: "user",
        type: "struct",
        children: [
          {
            name: "address",
            type: "struct",
            children: [{ name: "city", type: "string" }],
          },
        ],
      },
    ]);
    expect(tree).toHaveLength(3);
    expect(tree[1].children).toHaveLength(2);
    expect(tree[1].children![0]).toMatchObject({
      name: "amount",
      wire: "order.amount",
      path: ["order", "amount"],
    });
    const city = tree[2].children![0].children![0];
    expect(city).toMatchObject({
      name: "city",
      wire: "user.address.city",
      path: ["user", "address", "city"],
    });
  });

  it("returns [] for empty input", () => {
    expect(buildTree([])).toEqual([]);
  });
});

describe("buildTree from flat list (legacy)", () => {
  it("groups dot-form flat names into a trie", () => {
    const tree = buildTree([
      { name: "order.amount", type: "float64" },
      { name: "order.currency", type: "string" },
    ]);
    expect(tree).toHaveLength(1);
    expect(tree[0].name).toBe("order");
    expect(tree[0].children).toHaveLength(2);
    expect(tree[0].children![0]).toMatchObject({
      name: "amount",
      wire: "order.amount",
    });
  });

  it("keeps _dlt_* as flat top-level leaves", () => {
    const tree = buildTree([
      { name: "_dlt_id", type: "string" },
    ]);
    expect(tree[0].children).toBeUndefined();
    expect(tree[0].wire).toBe("_dlt_id");
  });
});

describe("findNode", () => {
  const tree = buildTree([
    { name: "id", type: "string" },
    {
      name: "user",
      type: "struct",
      children: [
        {
          name: "address",
          type: "struct",
          children: [{ name: "city", type: "string" }],
        },
      ],
    },
  ]);

  it("finds a top-level leaf", () => {
    expect(findNode(tree, "id")?.wire).toBe("id");
  });

  it("finds a nested leaf by dot-form wire", () => {
    expect(findNode(tree, "user.address.city")?.name).toBe("city");
  });

  it("returns null for unknown wire", () => {
    expect(findNode(tree, "nope")).toBeNull();
  });
});

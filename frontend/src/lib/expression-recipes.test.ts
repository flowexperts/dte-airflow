import { describe, expect, it } from "vitest";
import { RECIPES, buildRecipe, recipeById } from "./expression-recipes";

const build = (id: string, args: Record<string, string>) => buildRecipe(recipeById(id)!, args);

describe("buildRecipe", () => {
  it("returns empty until every required slot is filled", () => {
    expect(build("round", {})).toBe("");
    expect(build("round", { field: "amount" })).toBe('round("amount", 2)');
  });

  it("quotes identifiers, so a field with a quote cannot break out", () => {
    expect(build("length", { field: 'we"ird' })).toBe('length("we""ird")');
  });

  it("quotes text slots as string literals", () => {
    expect(build("replace", { field: "name", from: "O'Brien", to: "OBrien" })).toBe(
      `replace("name", 'O''Brien', 'OBrien')`,
    );
  });

  it("builds age from a field against the run date", () => {
    expect(build("age_years", { field: "dob", asof: "@today" })).toBe(
      `date_diff('year', "dob", CAST('{{today}}' AS DATE))`,
    );
  });

  it("builds age between two columns when asof is a field", () => {
    expect(build("age_years", { field: "dob", asof: "signup_at" })).toBe(
      `date_diff('year', "dob", "signup_at")`,
    );
  });

  it("guards division by zero in percent_of", () => {
    expect(build("percent_of", { field: "wins", of: "games" })).toBe(
      'round("wins" / NULLIF("games", 0) * 100, 2)',
    );
  });

  it("takes a literal or a field on the right of arithmetic", () => {
    expect(build("arithmetic", { field: "price", op: "*", other: "qty" })).toBe('"price" * "qty"');
    expect(build("arithmetic", { field: "price", op: "*", other: "1.2" })).toBe('"price" * 1.2');
  });

  it("defaults optional numeric slots rather than emitting nothing", () => {
    expect(build("substring", { field: "sku" })).toBe('substr("sku", 1, 5)');
  });
});

describe("RECIPES", () => {
  it("has unique ids", () => {
    expect(new Set(RECIPES.map((r) => r.id)).size).toBe(RECIPES.length);
  });

  /**
   * Plan 062 measured these four as hard failures outside DuckDB. A recipe
   * is a recommendation; recommending one of them would be recommending a
   * broken pipeline on any DB-backed source.
   */
  it("offers nothing measured to fail on another dialect", () => {
    const sql = RECIPES.map((r) =>
      buildRecipe(r, Object.fromEntries(r.args.map((a) => [a.key, "x"]))),
    ).join(" ");
    for (const bad of ["datepart(", "contains(", "string_split(", "try_cast("]) {
      expect(sql).not.toContain(bad);
    }
  });
});

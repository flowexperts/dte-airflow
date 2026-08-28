/**
 * `chartData` is the only real logic in the chart layer — everything else is
 * declarative recharts JSX. The three things it has to survive all come from
 * the preview endpoint being a *pipeline* response rather than a chart feed:
 *
 * 1. Numbers arrive as strings. DuckDB's `SUM(int)` is DECIMAL and the JSON
 *    writer stringifies decimals, so a bar chart fed straight from preview
 *    silently plots nothing — recharts drops non-numeric values and draws an
 *    empty grid with correct axes, which reads as "no data" rather than "wrong
 *    type".
 * 2. Rows are long-form when a `series` column is set; recharts wants wide.
 * 3. Nulls are ordinary in real data and must not become an "null" category.
 */
import { describe, it, expect } from "vitest";
import { chartData, seriesNames } from "./chart-data";

const spec = (over = {}) =>
  ({ kind: "bar", x: "region", y: ["revenue"], series: null, stacked: false, ...over }) as never;

describe("chartData", () => {
  it("passes simple rows through with numeric coercion", () => {
    const out = chartData(
      [
        { region: "EU", revenue: "1240.50" },
        { region: "US", revenue: 900 },
      ],
      spec(),
    );
    expect(out).toEqual([
      { region: "EU", revenue: 1240.5 },
      { region: "US", revenue: 900 },
    ]);
  });

  it("drops rows whose x is null", () => {
    const out = chartData(
      [
        { region: null, revenue: 10 },
        { region: "US", revenue: 20 },
      ],
      spec(),
    );
    expect(out).toEqual([{ region: "US", revenue: 20 }]);
  });

  it("keeps a null measure as null rather than zero", () => {
    // Zero is a value someone will read off the axis. A missing measure is
    // not zero revenue, and recharts renders a null as a gap.
    const out = chartData([{ region: "EU", revenue: null }], spec());
    expect(out[0]?.revenue).toBeNull();
  });

  it("pivots long rows to wide when series is set", () => {
    const out = chartData(
      [
        { day: "Mon", product: "A", units: 3 },
        { day: "Mon", product: "B", units: 5 },
        { day: "Tue", product: "A", units: 4 },
      ],
      spec({ kind: "line", x: "day", y: ["units"], series: "product" }),
    );
    expect(out).toEqual([
      { day: "Mon", A: 3, B: 5 },
      { day: "Tue", A: 4 },
    ]);
  });

  it("preserves first-seen order of x when pivoting", () => {
    // Chronological data arrives already ordered by the pipeline's sort
    // step. Re-sorting here would silently override it.
    const out = chartData(
      [
        { day: "Wed", product: "A", units: 1 },
        { day: "Mon", product: "A", units: 2 },
      ],
      spec({ kind: "line", x: "day", y: ["units"], series: "product" }),
    );
    expect(out.map((r) => r.day)).toEqual(["Wed", "Mon"]);
  });

  it("returns an empty array for no rows", () => {
    expect(chartData([], spec())).toEqual([]);
  });

  it("returns rows unchanged when the spec has no x", () => {
    // `number` and `table` kinds read rows directly.
    const rows = [{ total: "42" }];
    expect(chartData(rows, spec({ kind: "number", x: null, y: ["total"] }))).toEqual([
      { total: 42 },
    ]);
  });
});

describe("seriesNames", () => {
  it("lists the distinct series values in first-seen order", () => {
    const rows = [
      { day: "Mon", product: "B", units: 1 },
      { day: "Mon", product: "A", units: 2 },
      { day: "Tue", product: "B", units: 3 },
    ];
    expect(seriesNames(rows, spec({ x: "day", y: ["units"], series: "product" }))).toEqual([
      "B",
      "A",
    ]);
  });

  it("falls back to the y fields when there is no series column", () => {
    // Two measures on one chart are two series; the legend must name them.
    const s = spec({ kind: "line", x: "day", y: ["opened", "closed"], series: null });
    expect(seriesNames([], s)).toEqual(["opened", "closed"]);
  });
});

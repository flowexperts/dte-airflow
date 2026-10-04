/**
 * Drawing a tile (plan 064).
 *
 * Colours come from `--chart-1..6` in globals.css as CSS custom properties
 * used directly in SVG `fill` / `stroke`. That is why there is no theme
 * plumbing here: the browser resolves the variable per theme, so switching
 * light/dark repaints every mark with no React involvement and no risk of
 * the chart and the page disagreeing about which theme is active.
 *
 * The six steps are assigned **in fixed order and never cycled** — colour
 * follows the series, not its rank, so filtering one series out must not
 * repaint the survivors. A 7th series wraps, which is a legibility cliff;
 * the tile editor is where that should be prevented, by aggregating into an
 * "Other" bucket upstream.
 */
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/api";
import { chartData, seriesNames, type Row } from "./chart-data";

const PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];

// Non-null: the modulo keeps the index in range, but
// `noUncheckedIndexedAccess` cannot see that.
const colorAt = (i: number): string => PALETTE[i % PALETTE.length] ?? "var(--chart-1)";

/** Axis/grid ink stays in theme tokens — recessive, never a series colour. */
const AXIS = {
  stroke: "var(--border-2)",
  fontSize: 11,
  tick: { fill: "var(--muted)", fontSize: 11 },
};

const TOOLTIP_STYLE = {
  contentStyle: {
    background: "var(--surface-2)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    fontSize: 12,
    color: "var(--text)",
  },
  labelStyle: { color: "var(--muted)" },
  // Recharts' default hover fill is a translucent black that reads as a
  // dark smear on the dark theme.
  cursor: { fill: "var(--hover)" },
};

/** A big single figure. Formatted with the user's locale so 1240.5 reads
 *  as 1,240.5 — an unseparated number is the most common misread on a
 *  dashboard. */
function NumberTile({ rows, spec }: { rows: Row[]; spec: ChartSpec }) {
  const field = spec.y?.[0];
  const first = rows[0];
  const value = first && field ? (first[field] ?? null) : null;
  const display =
    typeof value === "number" ? value.toLocaleString() : value === null ? "—" : String(value);
  return (
    <div className="h-full flex flex-col items-center justify-center gap-1">
      <div className="text-4xl font-medium tabular-nums text-text">{display}</div>
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-subtle">
        {field}
      </div>
    </div>
  );
}

/** Falls back to whatever columns came back when `y` is empty, which is the
 *  `table` kind's whole point. */
function TableTile({ rows, spec }: { rows: Row[]; spec: ChartSpec }) {
  const columns = spec.y?.length ? spec.y : Object.keys(rows[0] ?? {});
  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-[12px] border-collapse">
        <thead>
          <tr className="text-left">
            {columns.map((c) => (
              <th
                key={c}
                className="sticky top-0 bg-surface border-b border-border py-1 pr-3 font-mono text-[10px] uppercase tracking-[0.14em] text-subtle font-normal"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border/50">
              {columns.map((c) => (
                <td key={c} className="py-1 pr-3 tabular-nums text-text">
                  {r[c] === null || r[c] === undefined ? "—" : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Chart({ rows, spec }: { rows: Row[]; spec: ChartSpec }) {
  const data = chartData(rows, spec);
  const keys = seriesNames(rows, spec);

  if (spec.kind === "number") return <NumberTile rows={data} spec={spec} />;
  if (spec.kind === "table") return <TableTile rows={data} spec={spec} />;

  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-[12px] text-subtle">
        No rows to plot
      </div>
    );
  }

  // A legend is always present for two or more series, so identity is never
  // carried by colour alone. One series needs none — the tile title names it.
  const legend = keys.length > 1 ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null;
  const grid = <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" vertical={false} />;
  const axes = (
    <>
      <XAxis {...(spec.x ? { dataKey: spec.x } : {})} {...AXIS} />
      <YAxis {...AXIS} width={44} />
    </>
  );

  if (spec.kind === "pie") {
    // Pie reads one measure across categories, so it uses the raw rows
    // rather than the pivot: each slice is a row, coloured by position.
    const field = spec.y?.[0];
    return (
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey={field ?? ""}
            {...(spec.x ? { nameKey: spec.x } : {})}
            innerRadius="45%"
            outerRadius="75%"
            // A 2px surface-coloured ring separates adjacent slices, which
            // is what keeps two similar values from reading as one wedge.
            stroke="var(--surface)"
            strokeWidth={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={colorAt(i)} />
            ))}
          </Pie>
          <Tooltip {...TOOLTIP_STYLE} cursor={false} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (spec.kind === "line") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          {grid}
          {axes}
          <Tooltip {...TOOLTIP_STYLE} cursor={{ stroke: "var(--border-2)" }} />
          {legend}
          {keys.map((k, i) => (
            <Line
              key={k}
              type="monotone"
              dataKey={k}
              stroke={colorAt(i)}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              // Nulls are gaps, not dives to zero — chart-data preserves
              // them for exactly this.
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (spec.kind === "area") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          {grid}
          {axes}
          <Tooltip {...TOOLTIP_STYLE} cursor={{ stroke: "var(--border-2)" }} />
          {legend}
          {keys.map((k, i) => (
            <Area
              key={k}
              type="monotone"
              dataKey={k}
              {...(spec.stacked ? { stackId: "1" } : {})}
              stroke={colorAt(i)}
              strokeWidth={2}
              fill={colorAt(i)}
              fillOpacity={0.18}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        {grid}
        {axes}
        <Tooltip {...TOOLTIP_STYLE} />
        {legend}
        {keys.map((k, i) => (
          <Bar
            key={k}
            dataKey={k}
            {...(spec.stacked ? { stackId: "1" } : {})}
            fill={colorAt(i)}
            // 4px rounded data-end, anchored to the baseline.
            radius={[4, 4, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

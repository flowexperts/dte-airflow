/**
 * Common map expressions as fill-in-the-slots recipes.
 *
 * The expression box is a raw DuckDB fragment: powerful, and useless if you
 * do not already know that "months between two dates" is spelled
 * `date_diff('month', a, b)`. A recipe is a labelled shape with typed slots
 * that composes exactly that fragment — the same relationship the Filter
 * Basic tab has to its WHERE clause. It generates text into the existing
 * expression field; it is not a step, not a mode, and nothing about it is
 * persisted.
 *
 * Two rules for what earns a place in this list:
 *
 * 1. **It transpiles.** Plan 062 measured 55 expressions against a live
 *    Postgres; `datepart`, `contains`, `string_split`, `len(array)` and
 *    `try_cast` are excluded because they fail or change meaning on another
 *    engine. A recipe is a recommendation, so the list only recommends what
 *    was measured to survive. `date_diff('year', …)` is the one knowingly
 *    kept divergence — it is the expression people actually come here for,
 *    and the dialect readback under the box names the divergence.
 * 2. **The name is the barrier.** `upper(x)` is here because "uppercase" is
 *    findable and `upper` is not. `a + b` is not worth a recipe.
 */
import { quoteIdent, safeLiteral, quoteString } from "./sql-literal";

/** A slot the user fills.
 *  - `field`    a column, picked from the step's schema
 *  - `dateref`  a column, or `@today` for the run date
 *  - `valueref` a column if it names one, otherwise a literal
 *  - `choice`   one of a fixed set, emitted verbatim (never user text)
 *  - `text`     free text, always emitted as a quoted string literal
 *  - `number`   free number; `fallback` fills it when left blank */
export type RecipeArg =
  | { kind: "field" | "dateref" | "valueref"; key: string; label: string; placeholder?: string }
  | { kind: "choice"; key: string; label: string; options: { value: string; label: string }[] }
  | { kind: "text"; key: string; label: string; placeholder?: string }
  | { kind: "number"; key: string; label: string; fallback: string };

export interface Recipe {
  id: string;
  label: string;
  group: "Dates" | "Text" | "Numbers" | "Nulls";
  /** One line, plain language — shown under the slots. */
  note: string;
  args: RecipeArg[];
  /** `a(key)` is the filled slot value — always a string. */
  build: (a: (key: string) => string) => string;
}

/** The run date, as the interpolator's sentinel. Quoted + cast rather than
 *  bare so it survives on a source whose engine will not coerce a string. */
const TODAY = `CAST('{{today}}' AS DATE)`;

const dateRef = (v: string) => (v === "@today" ? TODAY : quoteIdent(v));

/** A column reference if it looks like one, a literal otherwise. Numbers
 *  and quoted strings stay literals; anything else is treated as a column,
 *  which is what "other" reads as in `price * qty`. */
const valueRef = (v: string) =>
  /^-?\d+(\.\d+)?$/.test(v.trim()) || /^'.*'$/.test(v.trim())
    ? safeLiteral(v)
    : quoteIdent(v);

const DATE_UNITS = [
  { value: "day", label: "day" },
  { value: "week", label: "week" },
  { value: "month", label: "month" },
  { value: "quarter", label: "quarter" },
  { value: "year", label: "year" },
];

export const RECIPES: Recipe[] = [
  {
    id: "age_years",
    label: "Age / whole years between",
    group: "Dates",
    note: "Whole years from the first date to the second.",
    args: [
      { kind: "field", key: "field", label: "From date" },
      { kind: "dateref", key: "asof", label: "To" },
    ],
    build: (a) => `date_diff('year', ${quoteIdent(a("field"))}, ${dateRef(a("asof"))})`,
  },
  {
    id: "days_between",
    label: "Time between two dates",
    group: "Dates",
    note: "Counts whole units elapsed between the two dates.",
    args: [
      { kind: "choice", key: "unit", label: "Unit", options: DATE_UNITS },
      { kind: "field", key: "field", label: "From date" },
      { kind: "dateref", key: "to", label: "To" },
    ],
    build: (a) => `date_diff('${a("unit")}', ${quoteIdent(a("field"))}, ${dateRef(a("to"))})`,
  },
  {
    id: "date_bucket",
    label: "Round date down to period",
    group: "Dates",
    note: "Every date in the period collapses to the period's first day — the usual way to group by week or month.",
    args: [
      { kind: "field", key: "field", label: "Date" },
      { kind: "choice", key: "unit", label: "Period", options: DATE_UNITS },
    ],
    build: (a) => `date_trunc('${a("unit")}', ${quoteIdent(a("field"))})`,
  },
  {
    id: "date_part",
    label: "Pull one part out of a date",
    group: "Dates",
    note: "A number: the year, the month (1–12), the day of week (0 = Sunday).",
    args: [
      { kind: "field", key: "field", label: "Date" },
      {
        kind: "choice",
        key: "unit",
        label: "Part",
        options: [
          { value: "year", label: "year" },
          { value: "quarter", label: "quarter" },
          { value: "month", label: "month (1–12)" },
          { value: "day", label: "day of month" },
          { value: "dow", label: "day of week (0=Sun)" },
          { value: "hour", label: "hour" },
        ],
      },
    ],
    build: (a) => `extract(${a("unit")} from ${quoteIdent(a("field"))})`,
  },
  {
    id: "date_format",
    label: "Format a date as text",
    group: "Dates",
    note: "Text, not a date — good for labels and grouping keys.",
    args: [
      { kind: "field", key: "field", label: "Date" },
      {
        kind: "choice",
        key: "fmt",
        label: "Format",
        options: [
          { value: "%Y-%m-%d", label: "2026-08-27" },
          { value: "%Y-%m", label: "2026-08" },
          { value: "%Y", label: "2026" },
          { value: "%b %Y", label: "Aug 2026" },
        ],
      },
    ],
    build: (a) => `strftime(${quoteIdent(a("field"))}, '${a("fmt")}')`,
  },
  {
    id: "join_text",
    label: "Join two fields",
    group: "Text",
    note: "Glued together with the separator between them.",
    args: [
      { kind: "field", key: "field", label: "First" },
      { kind: "text", key: "sep", label: "Separator", placeholder: "leave blank for none" },
      { kind: "field", key: "second", label: "Second" },
    ],
    build: (a) =>
      `concat(${quoteIdent(a("field"))}, ${quoteString(a("sep"))}, ${quoteIdent(a("second"))})`,
  },
  {
    id: "change_case",
    label: "Change case / trim spaces",
    group: "Text",
    note: "Cleanup before a join or a group — mismatched case is the usual reason keys do not line up.",
    args: [
      {
        kind: "choice",
        key: "fn",
        label: "Do",
        options: [
          { value: "upper", label: "UPPERCASE" },
          { value: "lower", label: "lowercase" },
          { value: "trim", label: "trim spaces" },
        ],
      },
      { kind: "field", key: "field", label: "Field" },
    ],
    build: (a) => `${a("fn")}(${quoteIdent(a("field"))})`,
  },
  {
    id: "substring",
    label: "Take part of the text",
    group: "Text",
    note: "Positions start at 1.",
    args: [
      { kind: "field", key: "field", label: "Field" },
      { kind: "number", key: "start", label: "Start at", fallback: "1" },
      { kind: "number", key: "len", label: "Characters", fallback: "5" },
    ],
    build: (a) => `substr(${quoteIdent(a("field"))}, ${a("start")}, ${a("len")})`,
  },
  {
    id: "replace",
    label: "Find and replace",
    group: "Text",
    note: "Every occurrence, not just the first.",
    args: [
      { kind: "field", key: "field", label: "Field" },
      { kind: "text", key: "from", label: "Find" },
      { kind: "text", key: "to", label: "Replace with" },
    ],
    build: (a) =>
      `replace(${quoteIdent(a("field"))}, ${quoteString(a("from"))}, ${quoteString(a("to"))})`,
  },
  {
    id: "length",
    label: "Length of the text",
    group: "Text",
    note: "Number of characters.",
    args: [{ kind: "field", key: "field", label: "Field" }],
    build: (a) => `length(${quoteIdent(a("field"))})`,
  },
  {
    id: "round",
    label: "Round a number",
    group: "Numbers",
    args: [
      { kind: "field", key: "field", label: "Field" },
      { kind: "number", key: "places", label: "Decimal places", fallback: "2" },
    ],
    note: "0 places gives a whole number.",
    build: (a) => `round(${quoteIdent(a("field"))}, ${a("places")})`,
  },
  {
    id: "arithmetic",
    label: "Arithmetic on two values",
    group: "Numbers",
    note: "The second value can be another field or a fixed number.",
    args: [
      { kind: "field", key: "field", label: "Field" },
      {
        kind: "choice",
        key: "op",
        label: "Operation",
        options: ["+", "-", "*", "/"].map((o) => ({ value: o, label: o })),
      },
      { kind: "valueref", key: "other", label: "By", placeholder: "field or number" },
    ],
    build: (a) => `${quoteIdent(a("field"))} ${a("op")} ${valueRef(a("other"))}`,
  },
  {
    id: "percent_of",
    label: "Percentage of another field",
    group: "Numbers",
    note: "Rows where the total is 0 come out empty rather than failing the run.",
    args: [
      { kind: "field", key: "field", label: "Part" },
      { kind: "field", key: "of", label: "Total" },
    ],
    build: (a) =>
      `round(${quoteIdent(a("field"))} / NULLIF(${quoteIdent(a("of"))}, 0) * 100, 2)`,
  },
  {
    id: "coalesce",
    label: "Fall back when empty",
    group: "Nulls",
    note: "Uses the field, or the fallback when the field has no value.",
    args: [
      { kind: "field", key: "field", label: "Field" },
      { kind: "valueref", key: "fallback", label: "Fall back to", placeholder: "0 or 'unknown'" },
    ],
    build: (a) => `coalesce(${quoteIdent(a("field"))}, ${valueRef(a("fallback"))})`,
  },
];

export const recipeById = (id: string): Recipe | undefined =>
  RECIPES.find((r) => r.id === id);

/** Slots that may be left blank: `number` falls back, `text` is legitimately
 *  empty (replace-with-nothing, join-with-no-separator). */
const optional = (arg: RecipeArg) => arg.kind === "number" || arg.kind === "text";

/**
 * The fragment, or "" while a required slot is still empty.
 *
 * "" rather than a half-built string with a hole in it: this renders live on
 * every keystroke, and a preview of `round(, 2)` reads as a bug in the tool
 * rather than as an unfinished form.
 */
export function buildRecipe(recipe: Recipe, args: Record<string, string>): string {
  const filled: Record<string, string> = {};
  for (const arg of recipe.args) {
    const raw = (args[arg.key] ?? "").trim();
    if (!raw && !optional(arg)) return "";
    filled[arg.key] =
      raw || (arg.kind === "number" ? arg.fallback : arg.kind === "text" ? "" : "");
  }
  return recipe.build((k) => filled[k] ?? "");
}

/** Default slot values, so a freshly-picked recipe previews immediately
 *  instead of showing nothing until the last choice is made. */
export function recipeDefaults(recipe: Recipe): Record<string, string> {
  const out: Record<string, string> = {};
  for (const arg of recipe.args) {
    if (arg.kind === "choice") out[arg.key] = arg.options[0]!.value;
    else if (arg.kind === "number") out[arg.key] = arg.fallback;
    else if (arg.kind === "dateref") out[arg.key] = "@today";
  }
  return out;
}

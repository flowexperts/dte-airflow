/**
 * DuckDB literal/identifier quoting, shared by every surface that composes
 * a SQL fragment for the user: the Filter Basic tab, the `case` branch
 * rules, and the expression recipes. Raw user input never reaches a
 * fragment except through one of these.
 */

export function quoteIdent(name: string): string {
  return name
    .split(".")
    .map((seg) => `"${seg.replace(/"/g, '""')}"`)
    .join(".");
}

/** DuckDB string literal quote — wraps in '' and escapes internal ' as ''. */
export function quoteString(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

/**
 * Turn a value into a safe SQL literal.
 * Bare numbers (int or float) pass through as-is; everything else is quoted as string.
 * Never concatenates raw user input into the SQL string without going through here.
 */
export function safeLiteral(v: string): string {
  const trimmed = v.trim();
  if (trimmed === "") return "''";
  // {{params.X}} / {{today}} placeholders: quote so the resolved value
  // (ISO date/timestamp string) lands as a valid SQL literal. DuckDB
  // implicitly casts against the column type. Numeric comparisons still
  // work because DuckDB coerces string → number.
  if (/^\{\{[\w.]+\}\}$/.test(trimmed)) return `'${trimmed}'`;
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return trimmed;
  if (/^(true|false)$/i.test(trimmed)) return trimmed.toUpperCase();
  return quoteString(trimmed);
}

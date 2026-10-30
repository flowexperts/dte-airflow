"""Data-quality contract evaluator.

Evaluates a list of `Contract` instances against the pipeline's output target,
returning one `QualityResult` per contract.

Execution strategy
------------------
For file-based targets (json_file, csv_file, excel_file, parquet_s3) we create
a temporary DuckDB view over the output file so the shared ibis connection can
query it without re-loading. For database targets (postgres, sql_database) we
query the target table directly via the existing DuckDB scanner extensions.

All SQL goes through DuckDB; no ibis builder is used here because these queries
are parameterised by column names chosen at runtime.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from dte.models.quality import (
    ColumnInRange,
    ColumnMatches,
    ColumnNotNull,
    ColumnUnique,
    Contract,
    QualityResult,
    RowCountBetween,
)

# Targets name a format only; `path` may be local or an object-store URI, so
# the same reader works either way (the run already registered the SECRET).
_FORMAT_READER: dict[str, str] = {
    "json": "read_json_auto",
    "csv": "read_csv_auto",
    "excel": "read_xlsx",
    "parquet": "read_parquet",
}


def _view_sql_for_target(target) -> str:
    """Return a DuckDB SELECT expression that reads all rows from the target.

    Only file-based targets are supported today. Database targets are a
    stretch goal (plan 029 §Non-goals).
    """
    reader = _FORMAT_READER.get(target.type)
    if reader is None:
        raise NotImplementedError(
            f"Quality contracts are not yet supported for destination type "
            f"'{target.type}'. Supported types: {', '.join(_FORMAT_READER)}."
        )
    path = target.path.replace("'", "''")
    return f"SELECT * FROM {reader}('{path}')"


def _create_quality_view(con, target, view_name: str = "__dq_output__") -> None:
    """Materialise the target as a DuckDB view so all contract queries share it."""
    select_sql = _view_sql_for_target(target)
    # Use the underlying duckdb connection to bypass ibis's SQL dialect layer.
    raw = con.con  # ibis DuckDB backend exposes `.con` (the duckdb.DuckDBPyConnection)
    raw.execute(f"CREATE OR REPLACE TEMP VIEW {view_name} AS {select_sql}")


def _run_scalar(con, sql: str):
    """Execute a scalar SQL query and return the single value."""
    raw = con.con
    result = raw.execute(sql)
    row = result.fetchone()
    return row[0] if row else None


def evaluate_contracts(
    contracts: list,  # list[Contract] — kept loose to avoid circular imports at runtime
    target,           # OutputTarget
    con,              # ibis DuckDB backend (ibis.backends.duckdb.Backend)
) -> list[QualityResult]:
    """Evaluate every contract in `contracts` against `target`.

    Returns one `QualityResult` per contract, in the same order.
    """
    if not contracts:
        return []

    view = "__dq_output__"
    _create_quality_view(con, target, view)

    results: list[QualityResult] = []
    for contract in contracts:
        result = _evaluate_one(contract, view, con)
        results.append(result)
    return results


def _evaluate_one(contract: Contract, view: str, con) -> QualityResult:
    """Dispatch to the correct evaluator and return a QualityResult."""
    if isinstance(contract, RowCountBetween):
        return _eval_row_count_between(contract, view, con)
    if isinstance(contract, ColumnNotNull):
        return _eval_column_not_null(contract, view, con)
    if isinstance(contract, ColumnUnique):
        return _eval_column_unique(contract, view, con)
    if isinstance(contract, ColumnInRange):
        return _eval_column_in_range(contract, view, con)
    if isinstance(contract, ColumnMatches):
        return _eval_column_matches(contract, view, con)
    raise NotImplementedError(f"Unknown contract type: {type(contract)}")


def _eval_row_count_between(contract: RowCountBetween, view: str, con) -> QualityResult:
    count = _run_scalar(con, f"SELECT COUNT(*) FROM {view}")
    count = int(count) if count is not None else 0
    passed = contract.min <= count <= contract.max
    detail = f"{count} rows; expected between {contract.min} and {contract.max}"
    return QualityResult(
        contract_id=contract.id,
        contract_type=contract.type,
        passed=passed,
        severity=contract.severity,
        detail=detail,
    )


def _eval_column_not_null(contract: ColumnNotNull, view: str, con) -> QualityResult:
    col = contract.column.replace('"', '""')
    null_count = _run_scalar(
        con, f'SELECT COUNT(*) FROM {view} WHERE "{col}" IS NULL'
    )
    null_count = int(null_count) if null_count is not None else 0
    passed = null_count == 0
    detail = f"{null_count} null value(s) in column '{contract.column}'"
    return QualityResult(
        contract_id=contract.id,
        contract_type=contract.type,
        passed=passed,
        severity=contract.severity,
        detail=detail,
    )


def _eval_column_unique(contract: ColumnUnique, view: str, con) -> QualityResult:
    col = contract.column.replace('"', '""')
    # Count rows where the value appears more than once.
    dupe_count = _run_scalar(
        con,
        f'SELECT COUNT(*) FROM (SELECT "{col}", COUNT(*) AS cnt FROM {view} '
        f'GROUP BY "{col}" HAVING cnt > 1) sub',
    )
    dupe_count = int(dupe_count) if dupe_count is not None else 0
    passed = dupe_count == 0
    detail = f"{dupe_count} duplicate value(s) in column '{contract.column}'"
    return QualityResult(
        contract_id=contract.id,
        contract_type=contract.type,
        passed=passed,
        severity=contract.severity,
        detail=detail,
    )


def _eval_column_in_range(contract: ColumnInRange, view: str, con) -> QualityResult:
    col = contract.column.replace('"', '""')
    conditions = []
    if contract.min is not None:
        conditions.append(f'"{col}" < {contract.min}')
    if contract.max is not None:
        conditions.append(f'"{col}" > {contract.max}')

    if not conditions:
        # No bounds — trivially passes
        return QualityResult(
            contract_id=contract.id,
            contract_type=contract.type,
            passed=True,
            severity=contract.severity,
            detail="No range bounds specified; all rows pass",
        )

    where_clause = " OR ".join(f"({c})" for c in conditions)
    out_of_range = _run_scalar(
        con, f"SELECT COUNT(*) FROM {view} WHERE {where_clause}"
    )
    out_of_range = int(out_of_range) if out_of_range is not None else 0
    passed = out_of_range == 0
    bounds = []
    if contract.min is not None:
        bounds.append(f"min={contract.min}")
    if contract.max is not None:
        bounds.append(f"max={contract.max}")
    detail = (
        f"{out_of_range} value(s) out of range in column '{contract.column}' "
        f"({', '.join(bounds)})"
    )
    return QualityResult(
        contract_id=contract.id,
        contract_type=contract.type,
        passed=passed,
        severity=contract.severity,
        detail=detail,
    )


def _eval_column_matches(contract: ColumnMatches, view: str, con) -> QualityResult:
    col = contract.column.replace('"', '""')
    # DuckDB uses regexp_matches() for regex matching.
    regex = contract.regex.replace("'", "''")
    non_matching = _run_scalar(
        con,
        f"SELECT COUNT(*) FROM {view} "
        f"WHERE \"{col}\" IS NULL OR NOT regexp_matches(\"{col}\", '{regex}')",
    )
    non_matching = int(non_matching) if non_matching is not None else 0
    passed = non_matching == 0
    detail = (
        f"{non_matching} value(s) in column '{contract.column}' "
        f"do not match regex '{contract.regex}'"
    )
    return QualityResult(
        contract_id=contract.id,
        contract_type=contract.type,
        passed=passed,
        severity=contract.severity,
        detail=detail,
    )

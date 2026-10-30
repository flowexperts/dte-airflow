"""Keep provenance out of the deliverable without losing it.

The destination is the user's — it should contain their columns and nothing
else. `artifact_ref`, `extract_meta` and `structure_meta` are ours: internal
plumbing that makes a row checkable. Writing them into the customer's CSV was
the wrong side of that line.

So the compiled table is split at the writer boundary. User columns go to the
destination; system columns go to the artifact store, which is internal,
already holds the extract and structure caches, and already has eviction on
the roadmap. The database learns nothing new — the sidecar's key is derived
from the run id.

**Alignment is the whole risk here.** The output file has no row identity, so
the sidecar can only be rejoined by position — and two separate executions of
the same ibis expression give no ordering guarantee in DuckDB. Both sides
therefore read from *one* materialisation, stamped with an explicit row
number, and both order by it. Nothing here is safe if that materialisation is
skipped.
"""

from __future__ import annotations

import json

import ibis

from dte.artifacts import get_artifact_store, run_provenance_key
from dte.compiler.ibis_compiler import SYSTEM_COLUMNS

# Bound on how many rows carry provenance. 30k documents at roughly 300 bytes
# a row is ~9MB, which is unremarkable for a blob store; a million-row export
# is not. Past the cap rows simply have no provenance and the UI shows no
# Inspect affordance for them, which is honest — better than a sidecar that
# quietly becomes the largest object in the system.
MAX_PROVENANCE_ROWS = 50_000

_ROW_NO = "_dte_row_no"


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def system_columns_in(table: ibis.Table) -> list[str]:
    """Preserves the table's own column order, so the sidecar is stable."""
    return [c for c in table.columns if c in SYSTEM_COLUMNS]


def split_off_provenance(
    table: ibis.Table,
    run_id: str,
    con: ibis.BaseBackend | None = None,
) -> tuple[ibis.Table, str | None]:
    """Return `(table without system columns, sidecar key)`.

    Returns the table unchanged with a `None` key when there is no provenance
    to capture — the overwhelmingly common case, and it must stay free.
    """
    sys_cols = system_columns_in(table)
    if not sys_cols:
        return table, None

    backend = con if con is not None else table._find_backend()
    if not type(backend).__module__.startswith("ibis.backends.duckdb"):
        # Enrichment steps only run on DuckDB, so system columns cannot exist
        # on another backend. Degrade to a clean deliverable rather than
        # guessing at a materialisation strategy for an engine that will
        # never reach this line.
        return table.drop(*sys_cols), None

    raw = backend.con
    src = f"_dte_prov_src_{abs(hash(run_id)) % (1 << 30)}"
    tmp = f"_dte_prov_{abs(hash(run_id)) % (1 << 30)}"

    backend.create_view(src, table, overwrite=True)
    try:
        # One materialisation, one row numbering. Both the deliverable and the
        # sidecar are read from this table ordered by it, which is what makes
        # rejoining by position sound.
        raw.execute(f"DROP TABLE IF EXISTS {_ident(tmp)}")
        raw.execute(
            f"CREATE TEMP TABLE {_ident(tmp)} AS "  # quoted identifiers, int constant  # nosec B608
            f"SELECT *, row_number() OVER () AS {_ident(_ROW_NO)} "
            f"FROM {_ident(src)}"
        )
    finally:
        raw.execute(f"DROP VIEW IF EXISTS {_ident(src)}")

    cols = ", ".join(_ident(c) for c in sys_cols)
    rows = raw.execute(
        f"SELECT {cols} FROM {_ident(tmp)} "  # quoted identifiers, int constant  # nosec B608
        f"ORDER BY {_ident(_ROW_NO)} LIMIT {MAX_PROVENANCE_ROWS}"
    ).fetchall()

    payload = [dict(zip(sys_cols, r, strict=True)) for r in rows]
    key = run_provenance_key(run_id)
    get_artifact_store().put(
        key,
        json.dumps({"rows": payload}, default=str).encode("utf-8"),
        "application/json",
    )

    materialised = backend.table(tmp)
    return materialised.order_by(_ROW_NO).drop(_ROW_NO, *sys_cols), key


def read_provenance(run_id: str) -> list[dict]:
    """Sidecar rows in output order. Empty when the run predates this, wrote
    no documents, or has been evicted — all of which degrade to "no Inspect"
    rather than an error."""
    store = get_artifact_store()
    key = run_provenance_key(run_id)
    try:
        if not store.exists(key):
            return []
        payload = json.loads(store.get(key).decode("utf-8"))
    except (KeyError, ValueError):
        return []
    rows = payload.get("rows")
    return rows if isinstance(rows, list) else []

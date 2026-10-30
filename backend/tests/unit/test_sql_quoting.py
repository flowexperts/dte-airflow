"""Identifiers from pipeline config must be quoted, not spliced (plan 080)."""
import json

import ibis
import pandas as pd

from dte.compiler.ibis_compiler import _apply_profile
from dte.engine.duckdb_engine import DuckDBEngine
from dte.models.pipeline import Source
from dte.sources.loader import _load_documents


def test_profile_handles_quote_in_column_name():
    engine = DuckDBEngine()
    t = engine.con.create_table("p", pd.DataFrame({'we"ird': [1, 2, None]}))
    got = []
    _apply_profile(t, {"columns": ['we"ird']}, 0, engine, lambda i, r: got.append(r))
    assert json.loads(got[0].detail)["non_null"] == 2


def test_documents_table_name_with_quote(tmp_path):
    (tmp_path / "a.txt").write_text("hi")
    from dte.engine.backend_registry import BackendRegistry

    engine = DuckDBEngine()

    class Reg:
        def duckdb(self):
            return engine.con

    src = Source(
        id="d", kind="documents", table='do"c',
        config={"bucket_url": str(tmp_path), "file_glob": "*.txt"},
    )
    t = _load_documents(src, Reg(), None, {})
    assert t.count().execute() == 1

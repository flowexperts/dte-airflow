import json
import pandas as pd
import pyarrow.parquet as pq
import fsspec
import ibis
import pytest

from dte.engine.writers import write
from dte.models.pipeline import (
    JsonFileTarget,
    CsvFileTarget,
    ExcelFileTarget,
    ParquetS3Target,
)


@pytest.fixture
def sample_table():
    con = ibis.duckdb.connect()
    df = pd.DataFrame([
        {"id": 1, "name": "alice", "score": 90.5},
        {"id": 2, "name": "bob", "score": 42.0},
    ])
    con.create_table("t", df, overwrite=True)
    return con.table("t")


def test_json_file_writer(tmp_path, sample_table):
    out = tmp_path / "out.json"
    target = JsonFileTarget(type="json_file", path=str(out))
    result = write(sample_table, target)
    assert result["rows_written"] == 2
    assert result["location"] == str(out)
    data = json.loads(out.read_text())
    assert {r["name"] for r in data} == {"alice", "bob"}


def test_csv_file_writer(tmp_path, sample_table):
    out = tmp_path / "out.csv"
    target = CsvFileTarget(type="csv_file", path=str(out))
    result = write(sample_table, target)
    assert result["rows_written"] == 2
    assert result["location"] == str(out)
    text = out.read_text().strip().splitlines()
    assert text[0].split(",") == ["id", "name", "score"]
    assert len(text) == 3


def test_excel_file_writer(tmp_path, sample_table):
    out = tmp_path / "out.xlsx"
    target = ExcelFileTarget(type="excel_file", path=str(out))
    result = write(sample_table, target)
    assert result["rows_written"] == 2
    assert result["location"] == str(out)
    # Read back through DuckDB to avoid pulling in openpyxl at test time.
    reader = ibis.duckdb.connect()
    reader.raw_sql("INSTALL excel")
    reader.raw_sql("LOAD excel")
    df = reader.sql(f"SELECT * FROM read_xlsx('{out}')").execute()
    assert set(df.columns) == {"id", "name", "score"}
    assert sorted(df["name"].tolist()) == ["alice", "bob"]


def test_parquet_writer_memory_fs(sample_table):
    mem = fsspec.filesystem("memory")
    for path in list(mem.store):
        mem.rm(path)
    url = "memory://out.parquet"
    target = ParquetS3Target(type="parquet_s3", bucket_url=url)
    result = write(sample_table, target)
    assert result["rows_written"] == 2
    assert result["location"] == url
    with fsspec.open(url, "rb") as f:
        table = pq.read_table(f)
    assert table.num_rows == 2
    assert set(table.column_names) == {"id", "name", "score"}

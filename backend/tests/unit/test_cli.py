"""Plan 090: `dte validate` and `dte run` work on files, with no Postgres."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dte.cli import main

ORDERS = Path(__file__).parents[1] / "scenarios" / "fixtures" / "orders.json"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_validate_accepts_a_good_file(tmp_path, capsys):
    f = _write(tmp_path / "p1.yaml", "id: p1\nname: P\nsteps:\n- op: filter\n  expr: amount > 1\n")
    assert main(["validate", str(f)]) == 0
    assert "ok" in capsys.readouterr().out


def test_validate_rejects_a_bad_file_and_names_it(tmp_path, capsys):
    good = _write(tmp_path / "good.yaml", "id: good\nname: G\n")
    bad = _write(tmp_path / "bad.yaml", "id: bad\nname: B\nsteps:\n- op: nope\n")
    assert main(["validate", str(good), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "bad.yaml" in out and "nope" in out


def test_validate_rejects_an_id_that_is_not_the_file_name(tmp_path):
    f = _write(tmp_path / "a.yaml", "id: b\nname: B\n")
    assert main(["validate", str(f)]) == 1


def test_no_args_prints_usage():
    with pytest.raises(SystemExit) as e:
        main([])
    assert e.value.code != 0


def test_run_a_file_pipeline_from_the_cli_with_no_postgres(tmp_path):
    """filesystem source -> json file, connections from AIRFLOW_CONN_*."""
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(ORDERS, data / "orders.json")
    out = tmp_path / "out.json"
    repo = tmp_path / "repo"
    _write(repo / "sources" / "orders.yaml",
           f"id: orders\nsource_type: filesystem\nconnection_id: local_fs\ntable: orders\n"
           f"config:\n  bucket_url: {data}\n  file_glob: orders.json\n")
    _write(repo / "destinations" / "out.yaml",
           f"id: out\nconnection_id: local_fs\nconfig:\n  type: json_file\n  path: {out}\n")
    pipe = _write(repo / "big_orders.yaml",
                  "id: big_orders\nname: Big orders\nsources: [orders]\noutput_id: out\n"
                  "steps:\n- op: filter\n  expr: amount > 100\n")

    env = {k: v for k, v in os.environ.items() if not k.startswith(("DTE_", "AIRFLOW"))}
    env |= {
        "AIRFLOW_HOME": str(tmp_path / "airflow"),
        "AIRFLOW_CONN_LOCAL_FS": "fs://",
        # Unreachable: touching Postgres at all fails the run.
        "DTE_DATABASE_URL": "postgresql://nobody@127.0.0.1:1/none",
        "DTE_ARTIFACT_DIR": str(tmp_path / "artifacts"),
    }
    r = subprocess.run(
        [sys.executable, "-c", "import sys; from dte.cli import main; sys.exit(main())",
         "run", str(pipe), "--sample", "5"],
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=300,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    summary = json.loads(r.stdout[r.stdout.index("{\n"):])  # Airflow logs to stdout too
    assert summary["status"] == "completed"
    assert summary["rows_written"] == 5  # 9 match; --sample caps the rows
    rows = json.loads(out.read_text())
    assert len(rows) == 5 and all(float(row["amount"]) > 100 for row in rows)

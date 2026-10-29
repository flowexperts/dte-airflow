"""The wheel is the whole plugin: UI bundle and migrations included (plan 073)."""
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> zipfile.ZipFile:
    if not shutil.which("uv"):
        pytest.skip("uv not on PATH")
    src = tmp_path_factory.mktemp("src") / "backend"
    shutil.copytree(BACKEND, src, ignore=shutil.ignore_patterns(
        ".venv", "tests", "sample_data", "__pycache__", "*.pyc", "ui", "dist", ".dte-artifacts"))
    # Stand-in for the Vite build the release workflow copies here.
    (src / "dte" / "ui").mkdir()
    (src / "dte" / "ui" / "dte.umd.js").write_text("// bundle")
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "--wheel", "-q", "-o", str(out), str(src)], check=True)
    [whl] = out.glob("dte_airflow-*.whl")
    return zipfile.ZipFile(whl)


def test_wheel_ships_the_ui_bundle(wheel):
    assert "dte/ui/dte.umd.js" in wheel.namelist()


def test_wheel_ships_the_migrations(wheel):
    names = wheel.namelist()
    assert "dte/migrations/alembic.ini" in names
    assert "dte/migrations/alembic/env.py" in names
    versions = {p.name for p in (BACKEND / "alembic" / "versions").glob("*.py")}
    assert versions <= {Path(n).name for n in names if n.startswith("dte/migrations/alembic/versions/")}


def test_wheel_registers_the_plugin(wheel):
    [ep] = [n for n in wheel.namelist() if n.endswith("entry_points.txt")]
    text = wheel.read(ep).decode()
    assert "dte = dte.airflow.plugin:DtePlugin" in text
    assert "dte = dte.cli:main" in text

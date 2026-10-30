"""`dte db upgrade` — migrate DTE's `dte` schema in Airflow's metadata DB."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def db_upgrade() -> None:
    from alembic.config import Config

    from alembic import command
    from dte.airflow.db import sync_url

    # Installed wheel: dte/migrations. Repo checkout and the image: backend/.
    packaged = Path(__file__).resolve().parent / "migrations"
    root = Path(os.getenv("DTE_ALEMBIC_DIR") or (packaged if packaged.is_dir() else Path(__file__).resolve().parents[1]))
    # alembic/env.py reads DTE_DATABASE_URL as a *sync* URL.
    os.environ["DTE_DATABASE_URL"] = sync_url()
    command.upgrade(Config(str(root / "alembic.ini")), "head")


def main() -> None:
    if sys.argv[1:] == ["db", "upgrade"]:
        db_upgrade()
    else:
        sys.exit("usage: dte db upgrade")

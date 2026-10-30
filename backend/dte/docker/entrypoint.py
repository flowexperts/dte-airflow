"""Distroless-compatible entrypoint for the DTE backend container.

Distroless images have no shell, so the shell-script entrypoint
``docker/backend-entrypoint.sh`` cannot be used with the distroless runtime
stage.  This module replicates the same logic in pure Python:

1. If ``DTE_DATABASE_URL`` is set, strip ``+asyncpg`` and run
   ``alembic upgrade head`` as a subprocess.
2. ``os.execvp`` into uvicorn (replaces the current process so signals are
   forwarded correctly).
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:  # pragma: no cover — integration-only path
    db_url = os.environ.get("DTE_DATABASE_URL")
    if db_url:
        alembic_url = db_url.replace("+asyncpg", "")
        env = {**os.environ, "DTE_DATABASE_URL": alembic_url}
        print("Running alembic migrations…", flush=True)
        result = subprocess.run(
            [sys.executable, "-c", "from alembic.config import main; main(['upgrade', 'head'])"],
            env=env,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"alembic upgrade head failed (exit {result.returncode})", file=sys.stderr
            )
            return result.returncode

    # execvp replaces the current process — no return after this call.
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "dte.api.main:app",
            "--host",
            "0.0.0.0",  # nosec B104 - runs inside a container; must listen on all interfaces
            "--port",
            "8001",
        ],
    )
    # unreachable, but keeps type checkers happy
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Grant the seeded ``admin`` role to an existing user by email.

Operator recovery tool for the case where an operator's first-user register
lands after residual test users already exist in the DB — the register
handler grants ``admin`` only when the users table is empty, so the operator
would otherwise be locked out with no UI path.

Usage::

    DATABASE_URL=postgresql+asyncpg://... \\
        uv run python backend/scripts/promote_admin.py --email me@example.com

Exit codes:
  0  admin granted (or already present).
  1  no user with that email.
  2  DATABASE_URL missing.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dte.store.postgres import PostgresUserStore


async def _run(email: str) -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    users = PostgresUserStore(factory)
    user = await users.get_by_email(email)
    if user is None:
        print(f"No user with email {email!r}", file=sys.stderr)
        return 1
    if any(r.id == "admin" for r in user.roles):
        print(f"{email} already has admin", flush=True)
        return 0
    await users.add_role(user.id, "admin")
    print(f"Granted admin to {email} (id={user.id})", flush=True)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", required=True)
    args = p.parse_args()
    sys.exit(asyncio.run(_run(args.email)))


if __name__ == "__main__":
    main()

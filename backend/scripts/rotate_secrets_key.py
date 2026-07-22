"""Rotate the Fernet key used to encrypt Connection.credentials.

Reads every row from `connections`, decrypts under `--old-key`, re-encrypts
under `--new-key`, and writes back. Idempotent: re-running with the same
`--new-key` after an interrupted run picks up rows that still decrypt with
the *old* key and leaves the already-rotated rows alone (they will fail to
decrypt with the old key and be skipped with a warning).

Usage:

    uv run python scripts/rotate_secrets_key.py \
        --old-key "$OLD_KEY" \
        --new-key "$NEW_KEY" \
        --database-url "$DATABASE_URL"

After the script completes, set `DTE_SECRETS_KEY=$NEW_KEY` in the app's
environment and restart. The old key is safe to destroy once every row has
been rotated and no cold backups need to be decrypted with it.

Generate a new key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from cryptography.fernet import InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from dte.secrets.fernet import FernetSecretResolver


async def _rotate(old_key: str, new_key: str, database_url: str, dry_run: bool) -> int:
    old = FernetSecretResolver(old_key)
    new = FernetSecretResolver(new_key)
    engine = create_async_engine(database_url)
    rotated = skipped = failed = 0
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT id, credentials_encrypted FROM connections"))).all()
        print(f"found {len(rows)} connection rows")
        for row in rows:
            row_id, ciphertext = row
            if ciphertext is None:
                skipped += 1
                continue
            try:
                plaintext = old.decrypt(bytes(ciphertext))
            except InvalidToken:
                # Either already rotated (encrypts under new) or corrupt.
                try:
                    new.decrypt(bytes(ciphertext))
                    skipped += 1
                    print(f"  {row_id}: already rotated, skipping")
                    continue
                except InvalidToken:
                    failed += 1
                    print(f"  {row_id}: FAIL — does not decrypt under old or new key")
                    continue
            new_cipher = new.encrypt(plaintext)
            if not dry_run:
                await conn.execute(
                    text("UPDATE connections SET credentials_encrypted = :c WHERE id = :i"),
                    {"c": new_cipher, "i": row_id},
                )
            rotated += 1
            print(f"  {row_id}: rotated")
    await engine.dispose()
    print(f"\ndone — rotated={rotated} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-key", required=True)
    ap.add_argument("--new-key", required=True)
    ap.add_argument("--database-url", required=True, help="asyncpg URL, e.g. postgresql+asyncpg://…")
    ap.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")
    args = ap.parse_args()
    return asyncio.run(_rotate(args.old_key, args.new_key, args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())

# Secrets rotation

Rotate the Fernet key used to encrypt `connections.credentials_encrypted`
(BYTEA column, `EncryptedJSON` TypeDecorator, `FernetSecretResolver`).

Script: `backend/scripts/rotate_secrets_key.py`.

## When to rotate

- **Scheduled**: quarterly.
- **Incident-driven**:
  - Suspected or confirmed key exposure (leaked env dump, compromised host,
    accidental commit).
  - Employee offboarding where the departing engineer had access to
    `DTE_SECRETS_KEY` in any environment.
  - Any host that held the plaintext key is decommissioned or reimaged.

## Prerequisites

- **DB backup** of `connections` (pg_dump the table at minimum) before
  running with `--write`. Rotation mutates every row in place.
- **No downtime required.** The rotation is online:
  - Rows are read + rewritten one at a time inside a single transaction.
  - Rows already re-encrypted under the new key are skipped (idempotent).
  - The app keeps serving reads under the *old* key until you flip
    `DTE_SECRETS_KEY` and restart — do rotation first, promote second.
- Both keys held in memory of the operator shell only; never commit either
  to `.env`, git, or ticket comments.
- Confirm `DTE_DATABASE_URL` reachable from the operator host, asyncpg URL
  form: `postgresql+asyncpg://user:pass@host:5432/db`.

## Steps

### 1. Generate a new Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store the output in your secret manager immediately. This is the only
copy.

### 2. Export both keys for the rotation shell

```bash
export OLD_KEY="<current DTE_SECRETS_KEY value>"
export NEW_KEY="<value generated in step 1>"
export DTE_DATABASE_URL="postgresql+asyncpg://…"
```

The script takes both keys as CLI args (`--old-key`, `--new-key`). It does
**not** read `DTE_SECRETS_KEY` or a `DTE_SECRETS_KEY_NEW` env var — pass
them explicitly.

### 3. Dry-run

```bash
cd backend
uv run python scripts/rotate_secrets_key.py \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "$DTE_DATABASE_URL" \
    --dry-run
```

Expected output: `found N connection rows`, per-row `rotated` /
`already rotated, skipping`, then `done — rotated=X skipped=Y failed=0`.
Any `FAIL — does not decrypt under old or new key` line means a row is
corrupt or was encrypted under a third, unknown key. Investigate before
proceeding — do not `--write` until failed count is 0.

Exit code: `0` iff `failed == 0`.

### 4. Execute the rotation

Same command, drop `--dry-run`:

```bash
uv run python scripts/rotate_secrets_key.py \
    --old-key "$OLD_KEY" \
    --new-key "$NEW_KEY" \
    --database-url "$DTE_DATABASE_URL"
```

Idempotent: if the process is killed mid-run, re-run with the same args.
Already-rotated rows are detected via a probe decrypt under `--new-key`
and skipped.

### 5. Promote NEW to DTE_SECRETS_KEY

Update the running app's environment (secret manager, k8s Secret, compose
`.env`, whatever ships env vars):

```
DTE_SECRETS_KEY=<NEW_KEY value>
```

Restart the backend:

```bash
docker compose restart backend
```

or the equivalent in your deploy target.

### 6. Retire the old key

- Remove `OLD_KEY` from your local shell history (`unset OLD_KEY`).
- Delete the old key entry from the secret manager only after confirming
  no cold DB backup will need to be decrypted with it. Encrypted backups
  taken before rotation still require the old key to read.

## Verification

After the restart in step 5, hit the connection-test endpoint for at
least one connection of each type in use:

```bash
curl -X POST "http://localhost:8001/api/connections/<id>/test"
# → {"ok": true, "elapsed_ms": …, "detail": "…"}
```

A successful probe proves the app decrypted the credentials under the new
key and used them to reach the target. If `ok: false` with a decryption
error, revert per Rollback below.

Optional broader sweep:

```bash
curl "http://localhost:8001/api/connections" | jq '.[].id' \
  | xargs -I{} curl -s -X POST "http://localhost:8001/api/connections/{}/test"
```

## Rollback

The rotation script transacts row-by-row inside a single `engine.begin()`
block. Two failure modes:

1. **Script crashed / killed before completion.** No promotion happened
   yet, `DTE_SECRETS_KEY` still points at `OLD_KEY`, app still serving.
   Fix: re-run the same command — idempotent skip handles partial state.
   No rollback needed.

2. **Promotion (step 5) already happened, app can't decrypt some rows.**
   Revert `DTE_SECRETS_KEY` back to `OLD_KEY` and restart. Then run
   rotation in reverse to re-encrypt any rows that landed on the new key:

   ```bash
   uv run python scripts/rotate_secrets_key.py \
       --old-key "$NEW_KEY" \
       --new-key "$OLD_KEY" \
       --database-url "$DTE_DATABASE_URL"
   ```

   If the DB is unrecoverable, restore `connections` from the pg_dump
   taken in Prerequisites and set `DTE_SECRETS_KEY=$OLD_KEY`.

## Audit

Decrypt-audit logging is **P3 #36** and not yet shipped. There is no
per-decrypt log line today — rotation events should be recorded manually
in the ops journal (date, operator, key fingerprint, row counts from the
script output). Do not paste either key value into the journal.

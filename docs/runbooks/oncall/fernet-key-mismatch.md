# Runbook: Fernet key mismatch after rotation

**Symptom**: Immediately after running `rotate_secrets_key.py`, decrypt operations fail with `InvalidToken` on the Fernet decrypt path. Connection reads 500 with `credential_decrypt` failures in logs.

## First checks

1. Confirm which key is currently in `DTE_SECRETS_KEY`. If the env var got flipped to the new key before the rotation completed, half of rows are still encrypted under the old key.
2. Check the audit log:
   ```
   grep 'event=credential_decrypt' backend.log | tail -20
   ```
   Failed decrypts do NOT emit the audit line (only successes do — see `dte/secrets/encrypted_json.py`). Absence + `InvalidToken` exceptions is the signature.
3. Count affected connections:
   ```
   docker compose exec postgres psql -U dte -c "SELECT count(*) FROM connections;"
   ```

## Mitigation

1. **Roll back `DTE_SECRETS_KEY`** to the previous key value.
2. Restart the backend so the resolver picks up the old key.
3. Verify: `POST /api/connections/{id}/test` succeeds for a known-good connection.
4. Re-run rotation from a fresh dump per `docs/runbooks/secrets-rotation.md`, this time passing BOTH `--old-key` and `--new-key` explicitly.

## Root-cause hunts

- The rotation script is idempotent — probe-decrypts each row under the new key before rewriting. If it errored mid-run, some rows may already have been re-encrypted. Rolling back to the old key breaks those. Solution: identify by `updated_at` and hand-decrypt with the new key for the affected subset.
- If both keys are lost: **credentials are unrecoverable**. Customers must re-enter every Connection.

## Escalation

**Any Fernet mismatch touching prod is a P1 incident.** Post in `#dte-incident`, page the on-call lead, and start a customer-comms draft immediately.

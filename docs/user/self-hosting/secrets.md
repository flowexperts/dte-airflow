# Secrets & environment

dte stores connection credentials encrypted in Postgres. This page covers how encryption is keyed and how the env-indirection secret feature works.

## Env variables the backend reads

| Variable | Purpose | Notes |
| -------- | ------- | ----- |
| `DATABASE_URL` | Postgres connection string (async driver) | Required. `postgresql+asyncpg://…` |
| `DTE_SECRETS_BACKEND` | `env` or `fernet` — override the resolver | Optional. Falls back on `DTE_SECRETS_KEY`. |
| `DTE_SECRETS_KEY` | Fernet symmetric encryption key | Required in production. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `DTE_CORS_ORIGINS` | Comma-separated allowed origins for the API | Defaults to `http://localhost:3000`. |
| `NEXT_PUBLIC_API_URL` | Frontend → backend base URL | Baked at build time — rebuild the frontend after changing. |

## Two secret resolvers

Credentials on a `Connection` row are stored via a column-level encrypted JSON type. The **resolver** decides how encryption works.

- **Env resolver** (default in dev). Stores plaintext JSON. Values of the form `{"env": "FOO"}` are looked up in the process environment at decrypt time. Keeps real secrets in `.env` and only references in the DB.
- **Fernet resolver** (production). Symmetric encryption. Ciphertext at rest; the running process needs `DTE_SECRETS_KEY` to decrypt.

Selection order:

1. `DTE_SECRETS_BACKEND=env|fernet` — explicit.
2. `DTE_SECRETS_KEY` set → Fernet.
3. Otherwise → Env resolver. Emits a startup warning if `DATABASE_URL` is also set (production signal).

## Rotating a Fernet key

1. Decrypt every connection with the old key (write a small script that reads and re-saves each `Connection`).
2. Deploy the new `DTE_SECRETS_KEY`.
3. Re-save (the app will encrypt with the new key).

**Do not** change `DTE_SECRETS_KEY` without step 1 — the existing ciphertext becomes unreadable. If this happens, see the [Fernet key mismatch runbook](../../runbooks/oncall/fernet-key-mismatch.md).

## Env indirection in credential fields

Any credential field on a Connection accepts a reference instead of the literal value:

```json
{"aws_access_key_id": "AKIA…", "aws_secret_access_key": {"env": "AWS_SECRET_ACCESS_KEY"}}
```

`AWS_SECRET_ACCESS_KEY` must be set in the backend process environment. Handy for keeping real secrets in a secrets manager or `.env` and only references in the DB.

Works with both resolvers.

## What's in `.env`

`./scripts/bootstrap.sh` writes a starter `.env` with fresh values for `DATABASE_URL`, `DTE_SECRETS_KEY`, and the frontend URL. Don't commit it.

## External secret managers

For Vault, AWS Secrets Manager, GCP Secret Manager: implement a new resolver against the `SecretResolver` interface in `dte/secrets/`. The env and Fernet resolvers are examples.

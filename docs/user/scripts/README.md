# Docs screenshot pipeline

Two scripts, one driver:

- **`seed.py`** — writes a small demo dataset and creates a matching connection / source / destination / pipeline via the API.
- **`capture.ts`** — logs in via the API (no UI flakiness), then visits each route in `SHOTS` and screenshots it into `docs/user/assets/`.
- **`run.sh`** — one command that seeds, ensures Playwright's Chromium is installed, then captures.

## Full run

```bash
# 1. Bring the stack up
docker compose up -d --build

# 2. Sign up once (the first account becomes admin — a fresh install
#    auto-promotes the seed user; on an existing DB, grant admin manually).

# 3. Run everything
./docs/user/scripts/run.sh
```

If the demo user isn't the first account and thus has no permissions:

```bash
docker compose exec -T postgres psql -U dte -d dte -c \
  "INSERT INTO user_roles(user_id, role_id) \
   SELECT id, 'admin' FROM users WHERE email='demo@example.com' \
   ON CONFLICT DO NOTHING;"
```

## Env vars

| Var | Default | Notes |
| --- | ------- | ----- |
| `DTE_URL` (capture) | `http://localhost:3000` | Frontend base URL |
| `DTE_URL` (seed) | `http://localhost:8001` | Backend base URL |
| `DTE_API_URL` (capture) | `http://localhost:8001` | Backend base URL for login |
| `DTE_EMAIL` | `demo@example.com` | Shared by seed + capture |
| `DTE_PASSWORD` | `demopass1234` | Shared by seed + capture |
| `DTE_DATA_DIR` (seed) | `/tmp/dte-samples` | Where to write the demo JSON — must be a path the backend has mounted. |

## What gets shot

Keep `SHOTS` in `capture.ts` aligned with the `![](../assets/…)` references in `docs/user/**/*.md`.

`grep -rn '^!\[' docs/user | grep -v assets/scripts` gives the current list. Add a `SHOTS` entry per new reference.

## Screenshot conventions

- 1440×900 viewport, 2× device pixel ratio.
- Default theme (whatever the app boots into).
- No cursor overlays or annotations — keep the raw UI.
- File names mirror the docs path they're used in: `connections/new-local-fs.png` for `docs/user/getting-started/02-first-pipeline.md`.

## Regenerating

`./docs/user/scripts/run.sh` is idempotent — seed upserts, capture overwrites. Commit the diff on `docs/user/assets/` alongside any doc edit that changed a page.

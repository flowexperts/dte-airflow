# DTE demo recordings

Playwright-driven browser recordings of the DTE product for marketing / README use.

## User-flow demo (`record-user-flow.mjs`)

End-to-end tour: register → connection → source → destination → pipeline with
filter + sort + aggregate (preview refreshes after each save) → trigger run →
history + diff.

### Prereqs

```bash
docker compose up -d --build           # backend :8001, frontend :3000
curl -sf http://localhost:8001/healthz
curl -sf http://localhost:3000
```

`/tmp/dte-samples` must be bind-mounted into the backend (already wired in
`docker-compose.yml`). The script writes its fixture there before the
browser starts.

### Record + encode

```bash
cd scripts/demo
npm install                            # first time only
npx playwright install chromium        # first time only
node record-user-flow.mjs              # opens Chromium; ~2 min
./encode.sh 'out/webm/user-flow/*.webm' out/demo-user-flow
open out/demo-user-flow.mp4
open out/demo-user-flow.gif
```

### Knobs

Top of `record-user-flow.mjs`:

- `DWELL` — how long the cursor pauses on each narrative beat.
- `TYPE_DELAY` — ms per keystroke (deliberately slow for readability).
- `SLOWMO` — Playwright's global click / nav slowdown.
- `DEMO_BASE_URL` env var — override `http://localhost:3000`.

Every run uses a timestamped user + resource ids, so re-runs don't collide
and no cleanup is needed.

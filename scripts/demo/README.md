# DTE demo recordings

Playwright-driven browser recordings of the DTE product for marketing use.

| script | asset | length | what it shows |
|---|---|---|---|
| `record-core-join.mjs` | `out/demo-core-join.mp4` | ~3:00 | The flagship. Two sources, five tables, four joins, derived columns, Auto-map onto a drifted mart schema, a 27,691-row run. |
| `record-unstructured.mjs` | `out/demo-unstructured.mp4` | ~1:40 | PDF invoices → extract → structure → **Postgres**, then joined against the order system to surface two that disagree. |
| `record-cold-email.mjs` | `out/demo-cold-email-90s.mp4` | ~1:12 | The paste-into-a-cold-email cut. Same world, no build, hard 95s budget. |
| `record-user-flow.mjs` | `out/demo-user-flow.mp4` | ~2:00 | The original filesystem-JSON tour. **Currently broken** — see below. |

Shared harness lives in `lib.mjs`; every script imports its selectors,
caption overlay and timing knobs from there.

## Prereqs

```bash
# from the repo root
docker compose up -d --build          # incl. the postgres-demo service
./scripts/demo/verify.sh              # do not skip this
```

`verify.sh` seeds the control plane, runs all three pipelines, and prints
what Auto-map actually returns. It is the only thing standing between you
and discovering a dead beat with the camera rolling.

`ANTHROPIC_API_KEY` must be in `.env` — the `structure` step in
`record-unstructured.mjs` is a real model call, and Auto-map's third pass is
too. Without it Auto-map degrades to name matching and shows a gold
"the model pass did not run" banner, which reads as broken on camera.

## Record + encode

```bash
cd scripts/demo
npm install                            # first time only
npx playwright install chromium        # first time only

node record-core-join.mjs
./encode.sh 'out/webm/core-join/*.webm' out/demo-core-join
open out/demo-core-join.mp4
```

`out/` is gitignored — the encoded assets stay local until someone
deliberately copies one into `docs/user/assets/`.

`encode.sh` also writes a `.gif` beside the `.mp4`. At 1512px those run
11–26 MB, which is fine for the 72-second cold-email cut and much too big to
put in a README for the others. Take the GIF from the short one.

### Between takes

`record-core-join.mjs` and `record-cold-email.mjs` both **delete the select
step** from the seeded pipeline before recording, because with it in place
Auto-map reports "11 of 13, all 100% exact" — a wall of green that
demonstrates nothing. Without it Auto-map sees the raw joined column names
and returns 6 exact + 5 llm + 2 unmapped, which is a decision worth
watching someone make.

That deletion is not undone automatically. Re-seed before the next take:

```bash
python3 scripts/demo/seed-demo.py
```

### Reseeding the warehouse

The demo data is loaded by `seed/01-warehouse.sql` through postgres-demo's
`/docker-entrypoint-initdb.d` mount, which only fires on an **empty** data
directory. To pick up a change to that file:

```bash
docker compose rm -sfv postgres-demo && docker volume rm dte_demo_pgdata
docker compose up -d postgres-demo
```

## Knobs

Top of `lib.mjs`:

- `DWELL` — how long the cursor rests on each beat. Mutable; the cold-email
  cut reassigns it wholesale.
- `TIMING` — `typeDelay`, `clickPause`, `slowMo`.
- `VIEWPORT` — `null` by default, meaning "measure the real maximized window
  and match it exactly". Override with `DEMO_WIDTH` / `DEMO_HEIGHT`.
- `DEMO_BASE_URL` / `DEMO_API_URL` env vars.

Do not hardcode `VIEWPORT` to your display's resolution. `recordVideo`
captures at exactly the size it is given, and if the window is smaller the
frames get a grey letterbox band that cannot be cropped out afterwards.
A 3024px Retina panel reports 1512 CSS px, but Chrome's tab strip and
address bar take ~87px of that, so the usable page is 1512x862.
`--kiosk` looks like the fix and is not: it measured *smaller* (1200x818)
than `--start-maximized` on the same display.

## Known broken

`record-user-flow.mjs` fails at its first field: it types into a
`"Pipeline id"` input that no longer exists — pipeline ids became
server-generated UUIDs in plan 042, and `/pipelines/new` now shows only
`Name` and `Pipeline type`. It was already broken on `main` before the
`lib.mjs` refactor; the refactor only made the failure visible.

It is kept because the landing asset (`docs/user/assets/landing/dte-demo.webm`)
was cut from it. Either fix the two field references or delete it once the
landing page moves to `demo-core-join`.

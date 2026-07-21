# 025 — Landing page copy

Draft copy for the DTE marketing landing page. Edit inline; anything left unmarked is what gets written into `/tmp/dte-samples/landing.html` (and later ported to `frontend/src/app/(marketing)/`).

Design + layout are locked (dark theme, orange accent, Outfit + Space Mono + Cormorant italic wordmark). This file is copy only.

Core hook: **Map it once. Run it forever.**

---

## Nav

- Brand: `dte`
- Right: `Open app` (ghost) · `Book a call` (primary)

---

## Hero

**Eyebrow** — pick one:

1. Your data has 300 fields. Only one person on your team knows what they mean.
2. AI can write SQL. It still can't read your business.
3. The mapping is the hard part. Everything else runs itself.

**H1**:

> Transform Data
> Map it once.
> Run it forever.

**Lede** (2 sentences):

> Your domain expert maps the source — once, click by click. Your orchestrator runs it every day after.

**CTAs**:

- Primary: `Book a discovery call ↵`
- Ghost: `See it in motion`

**Meta strip** (below the CTAs):

`one mapping · many runs · any orchestrator`

**Right-hand animated viz** — a stack of step cards that shows the flow highlighting one by one
- 01 · Source · `s3://acme-orders/*.json` · filesystem
- 02 · Filter · `amount > 100` · expr
- 03 · Rename · `customer_id → cust_id` · rename
- 04 · Aggregate · `sum(amount) by cust_id` · group
- 05 · Join · `customers on cust_id` · left
- 06 · Destination · `postgres://warehouse.public.orders` · postgres

Status pill in the corner cycles `pending → running → ok` on a 2.4s loop.

---

## Section 5 — How it works

**Section eyebrow**: `How it works`

**H2**:

> Map. Save. Trigger.

**Sub**:

> Empty canvas to production in an afternoon.

**Step 1 — Map**
Your expert picks source, fields, destination. Previews against real rows.
Chip: `pick source · pick fields · pick destination`

**Step 2 — Save**
DTE stores the mapping as a versioned pipeline. Change your mind, change a step.
Chip: `versioned · preview · rollback`

**Step 3 — Trigger**
Your orchestrator hits `POST /trigger`. Every time. Forever.
Chip: `POST /trigger · GET /status · GET /output`

---

## Section 2 — The builder (animated pipeline)

**Section eyebrow**: `The builder`

**H2**:

> Stack your pipeline
> One step at a time

**Sub**:

> Pick columns. Pick operators. Ship the result. No code required

**Panel header (mono, small)**:

`orders_pipeline — 312 source fields · 6 mapped`

**Flow rows** (each reveals on scroll):

Linear left to right workflow of source, filter, lookup, map, aggregate, destination.
Add animations

---

## Section 3 — Integrations

**Section eyebrow**: `What you get`

**H2**:

> Pull data from anywhere
> Convert into anything

**Sub**:

Add tiles of all the sources currently supported and More... 

---

## Section 6 — Book a call

**Section eyebrow**: `Book a discovery call`

**H2**:

> See DTE on your data. 30 minutes.

**Body**:

> Bring your messiest source and the person who knows it. We'll map it live and hand you the API.

**Bullets**:

- Bring: one messy source and the expert who knows it.
- Leave with: a working pipeline plus the trigger URL.
- No sales pitch. Zero slides.

**Right side**: Cal.com embed (`bhavaniravi/dte-demo-call`, namespace `dte-demo-call`) — 660px height, wrapped in a Panel.

---

## Footer

- Left: `dte` · `map once, run forever`
- Right: `Open app` · `Book a call` · `© 2026`

---

## Title tag & meta

- `<title>`: `dte — map it once, run it forever`
- Description: `Your domain expert maps the source. Your orchestrator runs it. DTE is the layer in between.`

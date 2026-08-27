-- Demo warehouse for the recorded product demos.
--
-- Runs once, via postgres-demo's /docker-entrypoint-initdb.d mount, on an
-- empty data directory. To reseed:
--   docker compose rm -sfv postgres-demo && docker volume rm dte_demo_pgdata
--
-- Four schemas, standing in for four systems a real customer would have:
--   crm        the CRM              (customers, regions)
--   sales      the order system     (products, orders, order_items, vendor_bills)
--   staging    landing zone         (invoice_lines — written by the extract pipeline)
--   analytics  published marts      (order_facts, invoice_reconciliation)
--
-- All four live in ONE database on purpose. dte rejects a join whose sources
-- resolve to different ibis backends (_check_single_backend in
-- dte/compiler/ibis_compiler.py) and keys backends by Connection.id, so
-- "two databases" behind two connections could never be joined. Two schemas
-- behind one connection join fine, and push down into Postgres.
--
-- Every random() below is seeded (setseed) so a re-run reproduces the exact
-- same numbers. Recordings shot a week apart show the same row counts.

CREATE SCHEMA crm;
CREATE SCHEMA sales;
CREATE SCHEMA staging;
CREATE SCHEMA analytics;

-- ─── crm ──────────────────────────────────────────────────────────────────

CREATE TABLE crm.regions (
    region_code  text PRIMARY KEY,
    region_name  text NOT NULL,
    country      text NOT NULL
);

INSERT INTO crm.regions (region_code, region_name, country) VALUES
    ('NA-E',  'North America East', 'United States'),
    ('NA-W',  'North America West', 'United States'),
    ('EU-N',  'Northern Europe',    'Netherlands'),
    ('EU-S',  'Southern Europe',    'Spain'),
    ('APAC',  'Asia Pacific',       'Singapore'),
    ('LATAM', 'Latin America',      'Brazil');

CREATE TABLE crm.customers (
    customer_id  integer PRIMARY KEY,
    full_name    text NOT NULL,
    email        text NOT NULL,
    region_code  text NOT NULL REFERENCES crm.regions (region_code),
    signup_date  date NOT NULL,
    tier         text NOT NULL,
    is_active    boolean NOT NULL
);

SELECT setseed(0.42);
INSERT INTO crm.customers (customer_id, full_name, email, region_code, signup_date, tier, is_active)
SELECT
    i,
    (ARRAY['Ada','Bo','Cass','Dev','Eun','Fen','Gita','Hal','Ines','Jo',
           'Kit','Lior','Mira','Nils','Oona','Pax','Quin','Rhea','Sol','Tam'])
        [1 + (i * 7) % 20]
      || ' ' ||
    (ARRAY['Alvarez','Baptiste','Chen','Duarte','Eriksen','Freitas','Gupta',
           'Haugen','Iyer','Jensen','Kowalski','Lindqvist','Moreau','Nakamura',
           'Okafor','Petrov','Quintero','Rossi','Sandoval','Tanaka'])
        [1 + (i * 13) % 20],
    'customer' || i || '@example.com',
    (ARRAY['NA-E','NA-W','EU-N','EU-S','APAC','LATAM'])[1 + (i * 5) % 6],
    DATE '2022-01-01' + ((i * 17) % 1200),
    (ARRAY['free','pro','enterprise'])[1 + (i * 3) % 3],
    (i % 19) <> 0
FROM generate_series(1, 800) AS i;

-- ─── sales ────────────────────────────────────────────────────────────────

CREATE TABLE sales.products (
    product_id    integer PRIMARY KEY,
    product_name  text NOT NULL,
    category      text NOT NULL,
    -- `list_price`, not `unit_price`, so it does not collide with the price
    -- actually charged on sales.order_items. Two columns of the same name in
    -- one join get suffixed (`unit_price_right`) and that is unreadable on
    -- camera — and the distinction is real anyway: catalogue price vs. the
    -- price snapshotted onto the line at order time.
    list_price    numeric(10, 2) NOT NULL,
    discontinued  boolean NOT NULL
);

INSERT INTO sales.products (product_id, product_name, category, list_price, discontinued)
SELECT
    i,
    (ARRAY['Widget','Gadget','Doohickey','Thingamy','Whatsit','Sprocket',
           'Flange','Grommet'])[1 + (i * 3) % 8]
      || ' ' ||
    (ARRAY['Mini','Standard','Pro','Max','Lite'])[1 + (i * 7) % 5],
    (ARRAY['Hardware','Consumables','Accessories','Service'])[1 + (i * 5) % 4],
    round((12 + ((i * 37) % 1800) / 4.0)::numeric, 2),
    (i % 13) = 0
FROM generate_series(1, 40) AS i;

CREATE TABLE sales.orders (
    order_id      integer PRIMARY KEY,
    customer_id   integer NOT NULL REFERENCES crm.customers (customer_id),
    ordered_at    timestamp NOT NULL,
    status        text NOT NULL,
    currency      text NOT NULL,
    ship_country  text NOT NULL
);

INSERT INTO sales.orders (order_id, customer_id, ordered_at, status, currency, ship_country)
SELECT
    i,
    1 + (i * 11) % 800,
    TIMESTAMP '2024-01-01 00:00:00' + ((i * 43) % 700) * INTERVAL '1 day'
                                    + ((i * 97) % 86400) * INTERVAL '1 second',
    -- ~8% cancelled, so the filter step visibly removes rows on camera.
    CASE WHEN (i % 13) = 0 THEN 'cancelled'
         WHEN (i % 7)  = 0 THEN 'pending'
         WHEN (i % 5)  = 0 THEN 'shipped'
         ELSE 'paid' END,
    (ARRAY['USD','EUR','GBP'])[1 + (i * 3) % 3],
    (ARRAY['US','NL','ES','SG','BR','GB'])[1 + (i * 5) % 6]
FROM generate_series(1, 12000) AS i;

CREATE TABLE sales.order_items (
    order_item_id  integer PRIMARY KEY,
    order_id       integer NOT NULL REFERENCES sales.orders (order_id),
    product_id     integer NOT NULL REFERENCES sales.products (product_id),
    qty            integer NOT NULL,
    unit_price     numeric(10, 2) NOT NULL,
    discount_pct   numeric(5, 2) NOT NULL
);

-- 1–4 lines per order → ~30k rows. Line-level unit_price is snapshotted at
-- order time and drifts from the catalogue price on purpose: the demo's
-- line_total expression has to use the item's price, not the product's, and
-- that is a real modelling decision worth showing.
INSERT INTO sales.order_items (order_item_id, order_id, product_id, qty, unit_price, discount_pct)
SELECT
    row_number() OVER (),
    o.order_id,
    1 + ((o.order_id * 7 + n) % 40),
    1 + ((o.order_id + n) % 6),
    round((12 + (((1 + ((o.order_id * 7 + n) % 40)) * 37) % 1800) / 4.0)::numeric
          * (0.95 + ((o.order_id + n) % 11) / 100.0), 2),
    (ARRAY[0, 0, 0, 5, 10, 15, 25])[1 + (o.order_id + n) % 7]
FROM sales.orders o
CROSS JOIN LATERAL generate_series(1, 1 + (o.order_id % 4)) AS n;

-- Vendor bills the extracted invoice PDFs get reconciled against.
-- One row per distinct invoice number in
-- backend/sample_data/eval-demo/invoices/, carrying the CORRECT total.
--
-- The corpus ships two PDFs per invoice number, and for INV-1004 and INV-1005
-- the two disagree ($340.00 vs $412.75, $2,050.00 vs $12,000.00) — that
-- disagreement is built into the eval corpus, not manufactured here. Joining
-- 10 extracted rows to these 5 bills and filtering on variance therefore
-- lands on exactly 2 rows.
CREATE TABLE sales.vendor_bills (
    invoice_number  text PRIMARY KEY,
    vendor          text NOT NULL,
    bill_date       date NOT NULL,
    expected_total  numeric(12, 2) NOT NULL
);

INSERT INTO sales.vendor_bills (invoice_number, vendor, bill_date, expected_total) VALUES
    ('INV-1001', 'ACME Freight',       DATE '2026-03-01',  1240.50),
    ('INV-1002', 'ACME Freight',       DATE '2026-03-04',    87.00),
    ('INV-1003', 'Globex Shipping',    DATE '2026-03-11',  9999.99),
    ('INV-1004', 'Initech LLC',        DATE '2026-03-18',   340.00),
    ('INV-1005', 'Umbrella Transport', DATE '2026-03-22',  2050.00);

-- ─── staging ──────────────────────────────────────────────────────────────

-- Written by the `invoice_extract` pipeline (documents → extract → structure),
-- and pre-created empty because GET /api/destinations/{id}/schema introspects
-- real columns — without the table, Auto-map has nothing to map onto.
CREATE TABLE staging.invoice_lines (
    invoice_number  text,
    vendor          text,
    invoice_date    date,
    total           numeric(12, 2),
    freight         numeric(12, 2)
);

-- ─── analytics ────────────────────────────────────────────────────────────

-- The published mart. Some column names line up with what the pipeline
-- produces and some deliberately do not — which is what a real mart looks
-- like, and what Auto-map exists to absorb. A demo where every name already
-- matches proves nothing; one where none of them do reads as "the matcher
-- failed".
--
-- The split below is not a guess. It is what POST /api/schema/automap
-- actually returns against this pipeline's output (scripts/demo/verify.sh
-- reprints it, so a change to automap.py that spoils the demo is caught
-- before a recording session, not during one):
--
--   6 exact  @ 1.00 -> pre-ticked, since the dialog only auto-selects >= 0.9
--   5 llm    @ 0.60 -> correct, but each needs a deliberate click on camera
--   2 unmapped       -> nothing in the pipeline corresponds to them
--
-- Sensitive to renaming. `account_tier` was `customer_tier` first, and
-- difflib matched it to `customer_id` at 0.82 — confidently wrong, and it
-- beat the LLM pass to the field because fuzzy runs first.
CREATE TABLE analytics.order_facts (
    -- exact (1.00, pre-ticked)
    order_id          integer,
    ordered_at        timestamp,
    status            text,
    customer_name     text,
    region_name       text,
    quantity          integer,
    -- llm (0.60, unticked — the model reasons these out, you approve them)
    account_tier      text,           -- <- tier
    product_category  text,           -- <- category
    gross_amount      numeric(12, 2), -- <- line_total
    net_amount        numeric(12, 2), -- <- amount_after_discount
    size_band         text,           -- <- order_size
    -- No pipeline column corresponds to these. They stay `unmapped` in the
    -- dialog, which is the honest outcome and worth showing.
    source_system     text,
    loaded_at         timestamp
);

-- Target for the "build a pipeline from scratch" recording
-- (scripts/demo/record-build.mjs). Deliberately small: that video builds a
-- three-table join on camera, and mapping its output onto the 13-column
-- order_facts mart would leave most rows unmapped, which reads as failure
-- rather than as honesty.
--
-- Same drift trick as order_facts, scaled down — 3 exact, 2 the model has to
-- reason out, 1 with nothing behind it:
--   order_id / ordered_at / line_total  exact
--   customer_name <- full_name          llm
--   quantity      <- qty                llm
--   loaded_at                           unmapped
CREATE TABLE analytics.customer_orders (
    order_id       integer,
    ordered_at     timestamp,
    status         text,
    customer_name  text,
    quantity       integer,
    line_total     numeric(12, 2),
    loaded_at      timestamp
);

CREATE TABLE analytics.invoice_reconciliation (
    invoice_number  text,
    vendor          text,
    extracted_total numeric(12, 2),
    expected_total  numeric(12, 2),
    variance        numeric(12, 2)
);

-- Indexes on the join keys, so the pushdown query on camera is fast rather
-- than merely correct.
CREATE INDEX ON sales.order_items (order_id);
CREATE INDEX ON sales.order_items (product_id);
CREATE INDEX ON sales.orders (customer_id);
CREATE INDEX ON sales.orders (ordered_at);

GRANT USAGE ON SCHEMA crm, sales, staging, analytics TO demo;
GRANT ALL ON ALL TABLES IN SCHEMA crm, sales, staging, analytics TO demo;

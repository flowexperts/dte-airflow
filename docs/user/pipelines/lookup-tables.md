# Lookup tables

A small key → value reference table you attach to a pipeline: country code → country name, SKU → product line. Manage them under **Admin ▸ DTE Lookup tables**.

Use one when the mapping is small (dozens to a few thousand entries) and rarely changes. For anything big or authoritative, read it as a source and use a **Join** step.

## Create

**Admin ▸ DTE Lookup tables ▸ New**. Give it an id and a name, then add rows of **key** and **value**.

## Use

Add a **Map · lookup** step:

- Field: the column holding the key (e.g. `country_code`)
- Lookup table: the table to use
- Output field: where the value lands (e.g. `country_name`). Empty overwrites the input field.

A key missing from the table gives an empty output for that row.

# Field names

How to name a column in a step or destination.

## Simple

```
customer_id
amount
```

## Nested

Reach into nested JSON (and S3, GCS, Azure equivalents) with dots:

```
order.amount
user.address.city
```

The field picker lets you drill down and click.

## MongoDB and REST API

These sources flatten nested data with double underscores. Use the name as-is:

```
address__city
```

## Empty field picker

Click **Infer schema** on the source card.

## Result column names

A nested field written to the output is named after the **leaf** (`order.amount` → `amount`). Rename with an alias in the Select or Rename step, or the destination's field list.

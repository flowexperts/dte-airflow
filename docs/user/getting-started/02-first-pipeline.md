# Your first pipeline

Ten minutes. You'll read a folder of orders, keep only the paid ones, and write them out as a clean JSON file.

You'll make one of each thing: a connection, a source, a destination, and then a pipeline that uses them.

## 1. Add a connection

Connections are Airflow connections. Go to **Admin ▸ Connections ▸ Add connection** in Airflow:

- Connection Id: `local`
- Connection Type: **File (path)** (`fs`)

Save it. The `fs` type needs no credentials. dte reads and writes paths on the machines Airflow runs on. With the Docker Compose stack, `/tmp/dte-samples` is mounted for exactly this.

## 2. Add a source

Go to **Admin ▸ DTE Sources ▸ New**.

- Kind: **Filesystem**
- Connection: **local**
- Folder: `/tmp/dte-samples/` (it must be a folder, not a file)
- Files: `orders.json`
- Format: leave blank and dte detects it

Click **Infer schema**. dte reads a sample and shows the columns it found, such as `id`, `customer`, `status` and `amount`. If they don't look right, fix the folder or files field and try again.

## 3. Add a destination

Go to **Admin ▸ DTE Destinations ▸ New**.

- Type: **JSON file**
- Connection: **local**
- Path: `/tmp/dte-samples/out/orders_paid.json`

The extension has to match the type. If you type `.csv` here, dte stops you when you save.

## 4. Build the pipeline

Go to **Plugins ▸ DTE Pipelines ▸ Transform ▸ New pipeline**.

- Id: `orders_paid`. Keep it short with no spaces. The Airflow DAG is named after it: `dte__orders_paid`.
- Name: **Paid orders**
- Sources: pick your orders source
- Destination: pick the one you just made

Add two steps:

1. **Filter**: on the *Basic* tab, choose field `status`, operator `=`, value `paid`
2. **Select / Drop fields**: mode **Keep**, and tick `id`, `customer` and `amount`

Save. Within a few seconds Airflow's dag-processor picks up the new `dte__orders_paid` DAG.

## 5. Preview

The pipeline page shows a **Preview**: dte runs the steps on a small sample and shows the result. You should see only paid orders, with three columns.

If something's wrong, the preview turns red and says what. Fix the step and the preview updates.

## 6. Run

Click **▶ Run** and confirm. dte starts an Airflow dag run of `dte__orders_paid` and shows it right on the page as it goes from `pending` to `running` to `completed`. When it's done, your file has been written.

The same run is in Airflow too, under the DAG, with its task log.

That's it, you have a pipeline. Run it again tomorrow, or [give it a schedule](../pipelines/scheduling.md) and let Airflow run it for you.

## Next

- [Core ideas](03-concepts.md)
- [Steps reference](../steps/index.md): everything else you can do to data

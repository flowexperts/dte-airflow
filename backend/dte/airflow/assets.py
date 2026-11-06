"""Airflow Asset URIs for what a pipeline reads and writes (plan 089).

Airflow's Assets view is the lineage graph, and an "after upstream" schedule
triggers on these URIs, so a destination and a source naming the same table
must produce the same string.

- Files keep their own URL (`s3://…`, `gs://…`); a local path becomes `file://`.
- Tables are `dte://<conn_id>/<schema>/<table>`. Not `postgres://`: provider
  URI normalizers (postgres wants database/schema/table, mysql database/table)
  would reject a conn_id-based URI at parse time and break the DAG, and a
  source doesn't know its dialect without opening the connection.
- Only the conn_id ever goes in, never a URL from a connection secret; userinfo
  in a configured URL is dropped. No airflow import: the API lists these too.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def _location(path: str) -> str:
    if "://" not in path:
        return "file://" + ("" if path.startswith("/") else "/") + path
    p = urlsplit(path)
    return urlunsplit(p._replace(netloc=p.netloc.rpartition("@")[2]))


def asset_uri(obj, table: str | None = None) -> str | None:
    """URI for a `Destination`, or a `Source` plus the table a pipeline reads
    from it. None when there is nothing addressable (rest_api)."""
    cfg = obj.config
    cfg = cfg.model_dump(by_alias=True) if hasattr(cfg, "model_dump") else dict(cfg or {})
    kind = cfg.get("type") or getattr(obj, "source_type", None)
    if kind in ("postgres", "sql_database"):
        return f"dte://{obj.connection_id}/{cfg.get('schema') or 'default'}/{table or cfg.get('table') or obj.table}"
    if kind == "mongodb":
        return f"dte://{obj.connection_id}/{cfg['database']}/{cfg['collection']}"
    if kind == "kafka":
        return f"dte://{obj.connection_id}/kafka/{cfg['topic']}"
    if cfg.get("path"):
        return _location(cfg["path"])
    if cfg.get("bucket_url"):
        return _location(f"{cfg['bucket_url'].rstrip('/')}/{cfg.get('file_glob', '')}")
    return None


def lineage(config: dict, sources: dict, destinations: dict) -> tuple[list[str], list[str]]:
    """(inlets, outlets) URIs for a pipeline config, given Sources and
    Destinations by id. Missing ones are skipped: the run fails on them, the
    DAG shouldn't."""
    from dte.models.pipeline import coerce_source_refs

    inlets = [u for ref in coerce_source_refs(config.get("sources") or [])
              if (s := sources.get(ref.source_id)) and (u := asset_uri(s, ref.table))]
    outlets = []
    if (config.get("pipeline_type") or "transform") == "transform":
        d = destinations.get(config.get("output_id"))
        if d and (u := asset_uri(d)):
            outlets.append(u)
    return inlets, outlets


def kafka_watches(config: dict, sources: dict) -> list[dict]:
    """What a `messages` schedule watches (plan 108): per Kafka source, its
    Asset URI and the consumer group the run commits to."""
    from dte.models.pipeline import coerce_source_refs

    out = []
    for ref in coerce_source_refs(config.get("sources") or []):
        s = sources.get(ref.source_id)
        if s is None or s.source_type != "kafka":
            continue
        out.append({"uri": asset_uri(s), "conn_id": s.connection_id, "topic": s.config["topic"],
                    # Same default as the loader: the group the run commits to.
                    "group_id": s.config.get("group_id") or f"dte__{s.id}"})
    return out

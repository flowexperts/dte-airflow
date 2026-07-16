"""Extract credentials from legacy plan-015 sources / destinations into
plan-016 Connection rows.

Legacy shape:
- `Source.config` carried credentials inline (`aws_access_key_id`,
  `hmac_key_id`, `credentials` URL, `connection_url`, etc).
- `Destination.config` similarly carried `credentials` / `storage_options`.

Post-migration:
- Every unique credential blob becomes a Connection row.
- Sources / destinations lose those cred fields from `config` and gain a
  `connection_id` ref.
- Filesystem sources + json_file/csv_file destinations all share a
  singleton `local_fs_default` connection.

Idempotent — rows already in plan-016 shape pass through untouched.

Usage:
    cd backend
    uv run python scripts/migrate_extract_connections.py           # dry run
    uv run python scripts/migrate_extract_connections.py --write   # persist
"""
from __future__ import annotations
import argparse
import asyncio
import copy
import hashlib
import json


LOCAL_FS_DEFAULT_ID = "local_fs_default"


# ── cred extraction ─────────────────────────────────────────────────────

# (source_type / dest type) → (connection_type, cred_field_names)
_SOURCE_CREDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "filesystem": ("local_fs", ()),
    "s3": ("s3", ("aws_access_key_id", "aws_secret_access_key", "aws_session_token",
                  "region_name", "endpoint_url", "profile_name")),
    "gcs": ("gcs", ("hmac_key_id", "hmac_secret")),
    "azure": ("azure", ("azure_storage_account_name", "azure_storage_account_key",
                        "azure_storage_sas_token",
                        # legacy plan-014 field names — normalize here.
                        "connection_string", "account_name", "account_key")),
    "sql_database": ("postgres", ("credentials",)),  # ct refined by URL below
    "mongodb": ("mongodb", ("connection_url",)),
    "rest_api": ("rest_api", ()),  # rest_api creds sit under client.auth/headers
}

_DEST_CREDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "json_file": ("local_fs", ()),
    "csv_file": ("local_fs", ()),
    "parquet_s3": ("s3", ("storage_options",)),
    "postgres": ("postgres", ("credentials",)),
    "sql_database": ("mysql", ("credentials",)),  # ct refined by target.dialect
}


def _dedupe_key(creds: dict, connection_type: str) -> str:
    """Stable id fragment for identical credential blobs — same creds
    across many sources collapse to one Connection."""
    if not creds:
        return LOCAL_FS_DEFAULT_ID  # sentinel — ignored for local_fs
    blob = json.dumps(creds, sort_keys=True, default=str)
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]
    return f"conn_{connection_type}_{digest}"


def _normalize_azure_creds(creds: dict) -> dict:
    """Rewrite legacy plan-014 azure field names into dlt-aligned names."""
    out = {}
    if "azure_storage_account_name" in creds:
        out["azure_storage_account_name"] = creds["azure_storage_account_name"]
    elif "account_name" in creds:
        out["azure_storage_account_name"] = creds["account_name"]
    if "azure_storage_account_key" in creds:
        out["azure_storage_account_key"] = creds["azure_storage_account_key"]
    elif "account_key" in creds:
        out["azure_storage_account_key"] = creds["account_key"]
    if "azure_storage_sas_token" in creds:
        out["azure_storage_sas_token"] = creds["azure_storage_sas_token"]
    # `connection_string` was DuckDB-native pre-016; there's no direct dlt
    # equivalent. Preserve on the connection but flag it for the operator.
    if "connection_string" in creds:
        out["connection_string"] = creds["connection_string"]
    return out


def _extract_source_creds(source: dict) -> tuple[str, dict, dict]:
    """Return (connection_type, credentials, cleaned_config)."""
    st = source["source_type"]
    ct, cred_fields = _SOURCE_CREDS.get(st, (None, ()))
    if ct is None:
        raise ValueError(f"unknown source_type {st!r} in source {source['id']!r}")

    config = copy.deepcopy(source.get("config", {}))
    creds: dict = {}

    if st == "sql_database":
        raw_url = config.pop("credentials", None)
        if raw_url:
            creds["url"] = raw_url
            # Refine connection_type from URL scheme.
            for scheme, mapped in (
                ("postgres", "postgres"), ("postgresql", "postgres"),
                ("mysql", "mysql"), ("sqlite", "sqlite"),
            ):
                if isinstance(raw_url, str) and raw_url.startswith(f"{scheme}:"):
                    ct = mapped
                    break
    elif st == "mongodb":
        raw_url = config.pop("connection_url", None)
        if raw_url:
            creds["url"] = raw_url
    elif st == "azure":
        # Move known cred fields out of config, then normalize field names.
        raw = {k: config.pop(k) for k in list(config) if k in cred_fields}
        creds = _normalize_azure_creds(raw)
    elif st == "rest_api":
        client = config.get("client") or {}
        if "auth" in client:
            creds.setdefault("auth", client.pop("auth"))
        if "headers" in client:
            creds.setdefault("headers", client.pop("headers"))
    else:
        for k in list(config):
            if k in cred_fields:
                creds[k] = config.pop(k)

    return ct, creds, config


def _extract_destination_creds(destination: dict) -> tuple[str, dict, dict]:
    cfg = copy.deepcopy(destination.get("config", {}))
    t = cfg["type"]
    ct, cred_fields = _DEST_CREDS.get(t, (None, ()))
    if ct is None:
        raise ValueError(f"unknown destination type {t!r} in destination {destination['id']!r}")

    creds: dict = {}
    if t in ("postgres", "sql_database"):
        raw = cfg.pop("credentials", None)
        if raw:
            creds["url"] = raw
        if t == "sql_database":
            # Refine by dialect.
            dialect = cfg.get("dialect")
            if dialect in ("mysql", "snowflake", "bigquery"):
                ct = dialect
    elif t == "parquet_s3":
        so = cfg.pop("storage_options", None) or {}
        # fsspec/s3fs field names → dlt-aligned.
        alias = {
            "key": "aws_access_key_id",
            "secret": "aws_secret_access_key",
            "token": "aws_session_token",
        }
        for k, v in so.items():
            creds[alias.get(k, k)] = v

    return ct, creds, cfg


# ── migration ──────────────────────────────────────────────────────────

async def _upsert_connection(
    c_store,
    connection_type: str,
    credentials: dict,
    log: list[str],
) -> str:
    """Return the id used. Local_fs is a singleton across the fleet;
    everything else keys off a sha1 of the cred blob."""
    from dte.models.pipeline import ConnectionCreate
    if connection_type == "local_fs":
        if not await c_store.get(LOCAL_FS_DEFAULT_ID):
            await c_store.save(ConnectionCreate(
                id=LOCAL_FS_DEFAULT_ID,
                connection_type="local_fs",
                credentials={},
            ))
            log.append(f"  created shared connection {LOCAL_FS_DEFAULT_ID}")
        return LOCAL_FS_DEFAULT_ID

    cid = _dedupe_key(credentials, connection_type)
    if not await c_store.get(cid):
        await c_store.save(ConnectionCreate(
            id=cid,
            connection_type=connection_type,
            credentials=credentials,
        ))
        log.append(f"  created connection {cid} ({connection_type})")
    return cid


async def _migrate_source(source: dict, c_store, log: list[str]) -> tuple[dict, bool]:
    if source.get("connection_id"):
        return source, False
    ct, creds, cleaned_config = _extract_source_creds(source)
    cid = await _upsert_connection(c_store, ct, creds, log)
    updated = {**source, "connection_id": cid, "config": cleaned_config}
    return updated, True


async def _migrate_destination(destination: dict, c_store, log: list[str]) -> tuple[dict, bool]:
    if destination.get("connection_id"):
        return destination, False
    ct, creds, cleaned_config = _extract_destination_creds(destination)
    cid = await _upsert_connection(c_store, ct, creds, log)
    updated = {**destination, "connection_id": cid, "config": cleaned_config}
    return updated, True


async def main(write: bool) -> None:
    from dte.api.deps import (
        get_source_store, get_destination_store, get_connection_store,
    )
    s_store = get_source_store()
    d_store = get_destination_store()
    c_store = get_connection_store()

    changed_srcs = changed_dests = 0
    total_srcs = total_dests = 0

    for source in await s_store.list(limit=10_000):
        total_srcs += 1
        log: list[str] = []
        # `source` is a typed `Source` instance; convert to dict for
        # `_migrate_source` which works with plain dicts.
        src_dict = source.model_dump() if hasattr(source, "model_dump") else dict(source)
        updated, was_changed = await _migrate_source(src_dict, c_store, log)
        if not was_changed:
            continue
        changed_srcs += 1
        print(f"[source {src_dict['id']}] → connection_id={updated['connection_id']}")
        for line in log:
            print(line)
        if write:
            await s_store.save(updated)

    for destination in await d_store.list(limit=10_000):
        total_dests += 1
        log = []
        # `destination` is a typed `Destination` instance; convert to dict for
        # `_migrate_destination` which works with plain dicts.
        dest_dict = destination.to_api_dict() if hasattr(destination, "to_api_dict") else dict(destination)
        updated, was_changed = await _migrate_destination(dest_dict, c_store, log)
        if not was_changed:
            continue
        changed_dests += 1
        print(f"[destination {dest_dict['id']}] → connection_id={updated['connection_id']}")
        for line in log:
            print(line)
        if write:
            await d_store.save(updated)

    suffix = " — saved" if write else " (dry run; pass --write to persist)"
    print(
        f"\n{changed_srcs}/{total_srcs} sources changed, "
        f"{changed_dests}/{total_dests} destinations changed{suffix}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="Persist changes")
    args = ap.parse_args()
    asyncio.run(main(write=args.write))

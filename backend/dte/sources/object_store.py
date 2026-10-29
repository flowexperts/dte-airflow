"""Object storage through the installed Airflow provider (plan 074).

`ObjectStoragePath(url, conn_id=…)` asks the provider that owns the URL's
scheme (amazon for s3, google for gs, microsoft-azure for abfs/wasb, sftp,
…) for an fsspec filesystem, with every auth mode that provider supports.
DuckDB then reads and writes through it via `register_filesystem`.

DuckDB keys registered filesystems by protocol, so each connection gets its
own (`dte_<scheme>_<conn_id>`): two S3 connections can sit in one pipeline.
"""
from __future__ import annotations

import re

from fsspec.implementations.dirfs import DirFileSystem
from fsspec.spec import AbstractFileSystem

# Schemes DTE sources have always accepted -> the scheme the provider registers.
_ALIASES = {"gcs": "gs", "az": "abfs", "azure": "abfs"}


def _provider_fs(url: str, conn_id: str):
    from airflow.sdk import ObjectStoragePath

    return ObjectStoragePath(url, conn_id=conn_id).fs


class _Renamed(DirFileSystem):
    """Delegates every call to the provider's filesystem, under DTE's
    per-connection protocol; strips it so the provider sees `bucket/key`."""

    def __init__(self, fs, **kw):
        AbstractFileSystem.__init__(self, **kw)
        self.fs, self.path = fs, ""

    def _join(self, path):
        if isinstance(path, str):
            return self._strip_protocol(path)
        return [self._join(p) for p in path]


def register(raw_con, url: str, conn_id: str) -> str:
    """Register `conn_id`'s filesystem on this DuckDB connection; return the
    URL to hand DuckDB. Local paths come back unchanged."""
    scheme, sep, rest = url.partition("://")
    if not sep or scheme.lower() == "file":
        return url
    proto = re.sub(r"[^a-z0-9]+", "_", f"dte_{scheme}_{conn_id}".lower())
    if proto not in raw_con.list_filesystems():
        provider_url = f"{_ALIASES.get(scheme.lower(), scheme)}://{rest}"
        fs = type(proto, (_Renamed,), {"protocol": proto})(
            _provider_fs(provider_url, conn_id), skip_instance_cache=True)
        raw_con.register_filesystem(fs)
    return f"{proto}://{rest}"

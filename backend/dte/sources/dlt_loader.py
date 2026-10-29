"""Deprecated re-export shim for the module rename introduced in plan 015.

Use `dte.sources.loader` instead. This module will be removed after Task 7.
"""
from dte.sources.loader import *  # noqa: F401, F403
from dte.sources.loader import (  # noqa: F401
    LOADERS,
    _mongo_client,
    load_source,
    resolve_secret,
)

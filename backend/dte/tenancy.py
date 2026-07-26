"""Tenant context helpers.

A single `contextvars.ContextVar` holds the current tenant id for the
lifetime of a request (or background task). Middleware sets it at the
start of each request; stores read it when opening a Postgres session to
emit `SET LOCAL dte.tenant_id`.

Why contextvar and not a thread-local?
  asyncio tasks inherit a *copy* of the current context at creation time
  (CPython 3.7+). This gives natural isolation between concurrent requests
  and between the HTTP handler and the background `_execute_pipeline` task
  — as long as the task is spawned *after* the middleware has set the var,
  which is always true because trigger_pipeline runs inside the request
  handler.

  `contextvars.copy_context()` around `asyncio.create_task` is an
  extra belt-and-suspenders measure used in pipelines.py to be explicit.
"""
from __future__ import annotations

import contextvars

# Default is 'default' so get_current_tenant() always returns a valid string
# even when called outside a request context (migrations, scripts, tests).
tenant_context_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "dte_tenant_id", default="default"
)


def set_current_tenant(tid: str) -> contextvars.Token:
    """Set the tenant id for the current async context.

    Returns the Token produced by ContextVar.set() so the caller can
    reset the var when the context exits (use in a try/finally).
    """
    return tenant_context_var.set(tid)


def get_current_tenant() -> str:
    """Return the tenant id for the current async context.

    Falls back to 'default' when called outside a request (e.g. scripts).
    """
    return tenant_context_var.get()

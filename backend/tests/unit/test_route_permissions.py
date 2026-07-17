"""Safety net: every non-auth API route must gate on `requires(...)`.

Walks the FastAPI dependency tree of every registered route and asserts
that at least one dependency is the closure produced by
`dte.security.permissions.requires`. If someone adds a route without a
permission gate, this test fails in CI — no drift possible.
"""
from __future__ import annotations

import inspect

from dte.api.main import app
from dte.security.permissions import requires

# Sentinel used to identify closures produced by `requires(...)`. Any
# function whose `__qualname__` starts with `requires.` and lives in
# `dte.security.permissions` is one of ours.
_MARKER = "requires."


def _is_requires_dep(fn) -> bool:
    return (
        callable(fn)
        and getattr(fn, "__qualname__", "").startswith(_MARKER)
        and getattr(fn, "__module__", "") == "dte.security.permissions"
    )


def _dependency_call_chain(route) -> list:
    """Flatten the route's dependant tree so we see every dep function,
    including router-level ones. FastAPI wires them via `.dependant`."""
    out = []
    stack = [route.dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            out.append(d.call)
        stack.extend(d.dependencies)
    return out


# Routes deliberately outside the RBAC guard umbrella. Auth endpoints
# need to be reachable to log in; docs/openapi are metadata; healthcheck
# n/a here.
_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/me",   # gated by get_current_user only — no perm needed
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def _api_routes():
    from fastapi.routing import APIRoute
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        if r.path in _EXEMPT_PATHS:
            continue
        if not r.path.startswith("/api/"):
            continue
        yield r


def test_every_api_route_has_a_requires_dep():
    ungated = []
    for r in _api_routes():
        chain = _dependency_call_chain(r)
        if not any(_is_requires_dep(c) for c in chain):
            ungated.append(f"{','.join(sorted(r.methods))} {r.path}")
    assert not ungated, (
        "Routes missing `Depends(requires(...))`:\n  " + "\n  ".join(ungated)
    )


def test_requires_marker_is_findable():
    """Sanity check the introspection above — the closure `requires` returns
    must actually match the marker."""
    dep = requires("pipeline:read")
    assert _is_requires_dep(dep)

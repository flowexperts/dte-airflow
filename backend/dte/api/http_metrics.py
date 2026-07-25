"""Custom HTTP RED metrics middleware (P3 #30 — completes the item).

Replaces prometheus-fastapi-instrumentator, whose 7.1.0 crashes on FastAPI
0.115+ ``_IncludedRouter``. Emits the two RED metrics that matter for the
API-availability + API-latency SLOs (SLOs 3 and 4 in
``docs/observability/slos.md``):

- ``http_requests_total{method,route,status}`` — counter
- ``http_request_duration_seconds{method,route}`` — histogram

Route templates are resolved from the matched Starlette route so cardinality
stays bounded (e.g. ``/api/pipelines/{pipeline_id}``, not the literal id).
Unmatched requests get ``route="__unmatched__"`` to keep the label set finite.
"""
from __future__ import annotations

import time
from typing import Any

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

# Buckets tuned for API responses — dominated by sub-second, occasional slow
# preview / trigger up to a few seconds. Preview is excluded from SLO 4.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10)

http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests by method, matched route template, and status code",
    labelnames=("method", "route", "status"),
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    labelnames=("method", "route"),
    buckets=_LATENCY_BUCKETS,
)


def _match_route_template(request: Request) -> str:
    """Find the Starlette route pattern the request matched, or a sentinel.

    Walks the app's route tree recursively so nested Mounts / route groups
    resolve to their inner template (e.g. ``/api/pipelines/{pipeline_id}``),
    not the outer mount prefix.
    """

    def walk(routes, scope):
        for route in routes:
            try:
                match, child_scope = route.matches(scope)
            except Exception:  # noqa — never let metric routing raise
                continue
            if match != Match.FULL:
                continue
            # Mount / Router → recurse into children with the child scope
            # (which strips the mount prefix from the path).
            inner = getattr(route, "routes", None)
            if inner is not None:
                merged = {**scope, **child_scope}
                found = walk(inner, merged)
                if found is not None:
                    prefix = getattr(route, "path", "") or ""
                    return prefix + found if not found.startswith(prefix) else found
            path = getattr(route, "path", None)
            if isinstance(path, str):
                return path
        return None

    resolved = walk(request.app.routes, request.scope)
    return resolved or "__unmatched__"


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Skip /metrics itself — scraping the endpoint would double-count.
        path = request.url.path
        if path == "/metrics" or path.startswith("/metrics/"):
            return await call_next(request)

        started = time.perf_counter()
        status = 500  # pessimistic default; overwritten on the happy path
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            # Middleware error handler downstream will convert this into a
            # 5xx response; still record the failure with status=500.
            raise
        finally:
            elapsed = time.perf_counter() - started
            # Router sets scope["route"] after matching. Prefer that; fall
            # back to a recursive walk of app.routes (for cases where the
            # request short-circuited before the router ran).
            matched = request.scope.get("route")
            route = getattr(matched, "path", None) or _match_route_template(request)
            method = request.method
            http_requests_total.labels(method=method, route=route, status=str(status)).inc()
            http_request_duration_seconds.labels(method=method, route=route).observe(elapsed)

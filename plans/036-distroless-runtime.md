# Plan 036 — Distroless runtime image

Follow-up on the last remaining sub-item of P1 #18 in `plans/027-p0-p4-status-ladder.md`. Everything else on that item shipped (non-root user, resource limits, Trivy scan, `curl` removed, HEALTHCHECK instruction). Only distroless remains.

## Why it's not in the P1 #18 PR

Switching from `python:3.12-slim` to `gcr.io/distroless/python3-debian12:nonroot` looks small but has three coupled changes that each need care:

1. **Entrypoint rewrite.** Distroless has no shell — `backend/docker/backend-entrypoint.sh` cannot run. Must become a Python module (e.g. `dte/docker/entrypoint.py`) invoked via `ENTRYPOINT ["python", "-m", "dte.docker.entrypoint"]`.
2. **libpq copy.** Distroless ships glibc but not libpq5. Must `COPY --from=builder /usr/lib/x86_64-linux-gnu/libpq.so.5* /usr/lib/x86_64-linux-gnu/` (and any transitive deps like libgssapi_krb5, libldap). Getting the closure right needs `ldd` verification against the runtime image.
3. **User model.** Distroless nonroot is fixed to uid 65532. Our current image uses a synthesised `dte` uid. `chown -R 65532:65532 /app` in the builder stage instead of the runtime.

Each is tractable in isolation; the combination needs testing against a real Postgres to catch missing shared libs. Not a same-day close-out.

## Design

1. **Entrypoint** `backend/dte/docker/entrypoint.py`:

   ```python
   import os
   import sys
   import subprocess

   def main() -> int:
       db_url = os.environ.get("DATABASE_URL")
       if db_url:
           alembic_url = db_url.replace("+asyncpg", "")
           env = {**os.environ, "DATABASE_URL": alembic_url}
           r = subprocess.run(["alembic", "upgrade", "head"], env=env, check=False)
           if r.returncode != 0:
               return r.returncode
       os.execvp("uvicorn", [
           "uvicorn", "dte.api.main:app",
           "--host", "0.0.0.0", "--port", "8001",
       ])

   if __name__ == "__main__":
       sys.exit(main())
   ```

2. **Dockerfile runtime stage**:

   ```dockerfile
   FROM gcr.io/distroless/python3-debian12:nonroot AS runtime
   COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
   COPY --from=builder /usr/local/bin/alembic /usr/local/bin/alembic
   COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
   COPY --from=builder /app /app
   # libpq closure — verify with `ldd` on the builder stage first.
   COPY --from=builder /usr/lib/x86_64-linux-gnu/libpq.so.5* /usr/lib/x86_64-linux-gnu/
   # ...transitive .so files identified in step 3 of the task list
   WORKDIR /app
   USER nonroot
   EXPOSE 8001
   HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
       CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=2).status==200 else 1)"]
   ENTRYPOINT ["python", "-m", "dte.docker.entrypoint"]
   ```

3. **libpq closure** — capture in `docker/distroless-libs.txt`:
   - Build the current slim image.
   - `docker run --rm dte-backend ldd $(python -c "import psycopg2; print(psycopg2.__file__)" | xargs dirname)/*.so` — enumerate every `.so` under `/usr/lib`.
   - Diff against distroless's included libs, `COPY` the delta.

## Testing

- `docker build --target runtime` succeeds.
- Container starts against Docker Compose Postgres, `/healthz` returns 200 within 15 s.
- Full scenario suite passes against the distroless image (opt-in Docker-based CI job).
- Trivy scan of the distroless image reports fewer CVEs than the slim baseline.

## Task list

- `feature/distroless-entrypoint` — Python entrypoint + unit test.
- `feature/distroless-libs` — capture libpq closure, land in `docker/distroless-libs.txt`.
- `feature/distroless-dockerfile` — switch runtime stage, ship behind a `Dockerfile.distroless` first so we can A/B in CI before flipping the default.
- `feature/distroless-ci` — add a Docker CI job that runs a subset of scenarios against the distroless image.

## Non-goals

- Statically-linked Python distribution (not worth the maintenance).
- Rewriting alembic invocation as a Python API call — the CLI works fine under the new entrypoint.
- Rebasing on `chainguard/python` — same class of image, no compelling reason to switch vendors.

## Success criteria for closing P1 #18 fully

- Slim runtime removed from `backend/Dockerfile`; distroless is the default.
- Trivy CVE count drops (typically ~90% reduction vs slim).
- Compose stack + scenario suite green.

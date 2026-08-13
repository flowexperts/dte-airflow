FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY dte ./dte
COPY alembic ./alembic
COPY alembic.ini ./

# `[unstructured]` pulls pypdf + pdfplumber. Without it the image builds and
# starts fine, and then every `extract` step fails at runtime with "install the
# optional extra" — a failure that only shows up on a real document run.
RUN pip install --no-cache-dir -e ".[unstructured]" && pip install --no-cache-dir "psycopg2-binary>=2.9"

# Runtime stage — run as a non-root user for defence-in-depth.
# Distroless is deferred to plans/036-distroless-runtime.md; requires
# entrypoint rewrite from shell → Python and manual libpq copy.
FROM python:3.12-slim AS runtime

RUN groupadd --system dte && useradd --system --gid dte --no-create-home dte

# Runtime system deps: only libpq5. No curl, no build tools.
# HEALTHCHECK uses Python's urllib, not curl, so we don't need it here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed Python environment and application from the builder stage.
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

RUN chown -R dte:dte /app

COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

USER dte

EXPOSE 8001

# Standalone HEALTHCHECK (compose has its own too — both agree on /healthz).
# Uses Python because curl isn't installed.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=2).status==200 else 1)"

ENTRYPOINT ["backend-entrypoint.sh"]

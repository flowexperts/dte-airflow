# TODO (plan 027 P1 #18): consider switching to distroless/python for a smaller
# attack surface once the base-image change is scoped separately.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY dte ./dte
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir -e . && pip install --no-cache-dir "psycopg2-binary>=2.9"

# Runtime stage — run as a non-root user for defence-in-depth.
FROM python:3.12-slim AS runtime

RUN groupadd --system dte && useradd --system --gid dte --no-create-home dte

# Install runtime system deps (libpq only — no build tools).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed Python environment and application from the builder stage.
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Hand ownership of the app dir to the dte user.
RUN chown -R dte:dte /app

COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

USER dte

EXPOSE 8001

ENTRYPOINT ["backend-entrypoint.sh"]

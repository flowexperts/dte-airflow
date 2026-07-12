FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY dte ./dte
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --no-cache-dir -e . && pip install --no-cache-dir "psycopg2-binary>=2.9"

COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint.sh
RUN chmod +x /usr/local/bin/backend-entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["backend-entrypoint.sh"]

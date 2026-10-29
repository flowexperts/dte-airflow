# 073 — Install DTE into an existing Airflow with pip

Branch: `feature/pip-install` (off `dte-airflow`)

## Problem

DTE is an Airflow plugin by design (`airflow.plugins` and
`apache_airflow_provider` entry points), but the only way to run it is this
repo's Compose stack. Someone with their own Airflow 3.3 can't add it:

- It isn't on PyPI, and the name `dte` is taken there.
- A wheel ships without the UI. `Dockerfile.airflow` copies the Vite bundle to
  `backend/ui`, outside the `dte` package.
- A wheel ships without the migrations. `dte db upgrade` reads
  `backend/alembic.ini` and `backend/alembic/`, also outside the package.
- DTE's DAGs only run when they start unpaused. The stack sets
  `AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=False` globally, and an existing
  Airflow won't have it, so manual runs queue forever.
- Airflow 3.3's constraints pin `sqlglot==30`; DTE needs `<30`.

## Change

- Distribution name `dte-airflow`. `import dte` and the `dte` CLI stay.
- Wheel carries the UI at `dte/ui/` (hatch `artifacts`; the release build
  copies `frontend/dist` there) and the migrations at `dte/migrations/`
  (hatch `force-include` of `alembic.ini` + `alembic/`).
- `dte/api/main.py` serves `dte/ui/` when present, else the image's
  `backend/ui`. `dte/cli.py` reads `dte/migrations/` when present, else
  `backend/`. The Compose stack is unchanged.
- The DAG factory sets `is_paused_upon_creation=False` on every DTE DAG.
- sqlglot: install DTE without Airflow's constraints file (pip then resolves
  `sqlglot<30`), or strip the one pin, as the Dockerfile does. Documented.
- `.github/workflows/release.yml`: on a `v*` tag, build the UI, build the
  wheel and publish with PyPI trusted publishing. Never run from this branch.

## Tasks

1. Failing tests: wheel contains `dte/migrations/alembic.ini`, its versions
   and `dte/ui/*` when built; DTE DAGs are created unpaused.
2. Packaging, UI/migration lookup and the DAG flag.
3. `scripts/test-pip-install.sh`: build UI + wheel, pip install into a clean
   `apache/airflow:3.3.2` container against Postgres, run `dte db upgrade`,
   start the api-server, and check the plugin, UI bundle and API respond.
4. Docs: `docs/user/self-hosting/install-plugin.md`, README quickstart.
5. Site quickstart (in `feature/site-oss`) becomes the pip install.

## Files

`backend/pyproject.toml`, `backend/dte/api/main.py`, `backend/dte/cli.py`,
`backend/dte/airflow/{dag_factory,provider}.py`, `.gitignore`,
`.github/workflows/release.yml`, `scripts/test-pip-install.sh`,
`backend/tests/unit/test_packaging.py`, README, `docs/user/self-hosting/`.

## Manual, before the first release

- Create the `dte-airflow` project on PyPI with a trusted publisher for
  `flowexperts/dte-airflow`, workflow `release.yml`, environment `pypi`.

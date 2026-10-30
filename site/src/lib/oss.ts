/** The open-source projects DTE is built on. `core` ones show on the landing
 *  page; all of them on /open-source/. Licenses are from each package's own
 *  metadata — re-check when a dependency changes. */
export type Oss = { name: string; url: string; license: string; role: string; core?: boolean };

export const OSS_GROUPS: { title: string; items: Oss[] }[] = [
  {
    title: "Orchestration",
    items: [
      { name: "Apache Airflow", url: "https://airflow.apache.org", license: "Apache-2.0", role: "Schedules, runs and records every pipeline, and owns login and connections", core: true },
      { name: "Airflow providers", url: "https://airflow.apache.org/docs/apache-airflow-providers/", license: "Apache-2.0", role: "Authenticate every source and destination" },
    ],
  },
  {
    title: "Engine",
    items: [
      { name: "DuckDB", url: "https://duckdb.org", license: "MIT", role: "Executes each step, in process, on the Airflow worker", core: true },
      { name: "ibis", url: "https://ibis-project.org", license: "Apache-2.0", role: "Compiles steps to SQL and pushes work down to your database", core: true },
      { name: "sqlglot", url: "https://github.com/tobymao/sqlglot", license: "MIT", role: "Translates SQL between dialects", core: true },
      { name: "Apache Arrow", url: "https://arrow.apache.org", license: "Apache-2.0", role: "Moves tables between the engine and the writers" },
    ],
  },
  {
    title: "Loading",
    items: [
      { name: "dlt", url: "https://dlthub.com", license: "Apache-2.0", role: "Loads REST APIs and MongoDB, and writes to SQL destinations", core: true },
      { name: "fsspec", url: "https://filesystem-spec.readthedocs.io", license: "BSD-3-Clause", role: "Reads and writes S3, GCS, Azure and SFTP" },
      { name: "pypdf", url: "https://github.com/py-pdf/pypdf", license: "BSD-3-Clause", role: "Extracts text from PDFs" },
      { name: "pdfplumber", url: "https://github.com/jsvine/pdfplumber", license: "MIT", role: "Extracts text and layout from PDFs" },
    ],
  },
  {
    title: "Storage and API",
    items: [
      { name: "PostgreSQL", url: "https://www.postgresql.org", license: "PostgreSQL", role: "Stores pipelines, sources and run results" },
      { name: "FastAPI", url: "https://fastapi.tiangolo.com", license: "MIT", role: "Serves the API Airflow mounts at /dte" },
      { name: "Pydantic", url: "https://docs.pydantic.dev", license: "MIT", role: "Defines and validates every pipeline" },
      { name: "SQLAlchemy, SQLModel, Alembic", url: "https://www.sqlalchemy.org", license: "MIT", role: "The store and its migrations" },
    ],
  },
  {
    title: "UI, site and docs",
    items: [
      { name: "React", url: "https://react.dev", license: "MIT", role: "The pipeline builder inside Airflow" },
      { name: "PDF.js", url: "https://mozilla.github.io/pdf.js/", license: "Apache-2.0", role: "Renders documents in the builder" },
      { name: "Recharts", url: "https://recharts.org", license: "MIT", role: "Charts on the dashboard" },
      { name: "Vite, Tailwind CSS", url: "https://vite.dev", license: "MIT", role: "Build and styling" },
      { name: "Next.js, VitePress", url: "https://nextjs.org", license: "MIT", role: "This site and the docs" },
    ],
  },
];

export const CORE_OSS = OSS_GROUPS.flatMap((g) => g.items).filter((o) => o.core);

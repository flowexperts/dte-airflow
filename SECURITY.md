# Security policy

DTE is in **beta**. Only the latest release on `main` gets security fixes.

## Reporting a vulnerability

Please **do not open a public issue.** Report it privately through GitHub:
**Security → Report a vulnerability** on
[flowexperts/dte-airflow](https://github.com/flowexperts/dte-airflow/security/advisories/new).

Include what you found, how to reproduce it, and the version or commit.
You'll get an acknowledgement within 3 business days. We'll agree on a
disclosure date with you once a fix is ready, and credit you in the advisory
unless you'd rather not be named.

## Scope notes

- `docker-compose.yml` is a **local** stack. It binds to `127.0.0.1` and
  refuses to start without the secrets `scripts/bootstrap.sh` generates. Using it
  as-is on a server isn't a supported deployment.
- Credentials live in Airflow Connections and are encrypted with Airflow's
  Fernet key. Protect that key the same way you protect your Airflow deployment.

# Contributing

Thanks for your interest. DTE is in **beta** and moving fast, so contributions
work a little differently for now.

## Issues and discussions: open to everyone

- **Bugs:** open an issue with steps to reproduce, the commit or version, and
  your Airflow version.
- **Questions, ideas, "does it support X?":** use
  [Discussions](https://github.com/flowexperts/dte-airflow/discussions).
- **Security issues:** see [SECURITY.md](./SECURITY.md). Never use a public issue.

Issues are triaged within 3 business days. That's a promise to look at it,
not to fix it.

## Pull requests: approved contributors only

During beta, PRs are accepted only from repository collaborators. PRs from
anyone else are closed automatically. That isn't a judgement on the work: the
internals still change too often to review outside code fairly. If you want to
help, start a Discussion. If it's a fit, we'll add you as a collaborator.

New sources and destinations need a concrete use case first. Raise it in
Discussions before writing code.

## For approved contributors

- One change per branch, each with a plan in `plans/<NNN>-<name>.md` (see
  existing plans for the shape).
- Tests first. The tiers and commands are in the [README](./README.md#testing).
- Breaking changes are allowed during 0.x, but each one gets a line in the
  release notes and a migration note.
- By submitting a PR you agree your contribution is licensed under
  [Apache-2.0](./LICENSE), and you certify the
  [Developer Certificate of Origin](https://developercertificate.org/). Sign off
  your commits with `git commit -s`.

## Code of conduct

Everyone in this project follows the [Code of Conduct](./CODE_OF_CONDUCT.md).

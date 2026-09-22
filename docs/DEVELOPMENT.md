# Development

Use Python 3.12/3.13 and `./scripts/bootstrap.ps1`. Run `./scripts/check.ps1` before proposing a change. Keep changes typed, use Pydantic validation at boundaries, and add an Alembic revision for persistent schema changes. Do not write user data to the source checkout and never add real `.env`, database, attachments, or reference documents to commits.
